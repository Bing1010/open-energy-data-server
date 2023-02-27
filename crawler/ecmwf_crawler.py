from sqlalchemy import create_engine, text
from datetime import date, datetime, timedelta
import cdsapi
import pandas as pd
import os
import logging
import xarray as xr
import geopandas as gpd
from shapely.geometry import Point
import csv
from io import StringIO

"""
    Note that only rquests with no more that 1000 items at a time are valid.
    See the following link for further information:
    https://confluence.ecmwf.int/pages/viewpage.action?pageId=308052947

    Also "Surface net solar radiation" got renamed to "Surface net short-wave (solar) radiation"
"""

logging.basicConfig(filename='ecmwf.log', encoding='utf-8', level=logging.DEBUG)
log = logging.getLogger('ecmwf')

c = cdsapi.Client()  # --> client for ECMWF-Service

# fallback date if a new crawl is started
default_start_date = datetime(2020, 1, 1, 0, 0, 0)

db_uri = f'postgresql://opendata:opendata@10.13.10.41:5432/weather'

# path of nuts file
nuts_path = os.path.realpath(os.path.join(os.path.dirname(__file__), 'shapes', 'NUTS_RG_01M_2021_4326.shp'))

# coords for europe according to:
# https://cds.climate.copernicus.eu/toolbox/doc/how-to/1_how_to_retrieve_data/1_how_to_retrieve_data.html#retrieve-a-geographical-subset-and-change-the-default-resolution
coords = [75, -15, 30, 42.5]

# requested weather variable
var_ = ['10m_u_component_of_wind',
        '10m_v_component_of_wind',
        '2m_temperature',
        'total_precipitation ',
        'surface_net_solar_radiation']


def create_table(engine):
    try:
        query_create_hypertable = "SELECT create_hypertable('ecmwf_neu', 'time', if_not_exists => TRUE, migrate_data => TRUE);"
        query_create_hypertable_eu = "SELECT create_hypertable('ecmwf_neu_eu', 'time', if_not_exists => TRUE, migrate_data => TRUE);"
        with engine.connect() as conn, conn.begin():
            conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS ecmwf_neu( "
                                 "time timestamp without time zone NOT NULL, "
                                 "temp_air double precision, "
                                 "ghi double precision, "
                                 "wind_meridional double precision, "
                                 "wind_zonal double precision, "
                                 "wind_speed double precision, "
                                 "precipitation double precision, "
                                 "latitude double precision, "
                                 "longitude double precision, "
                                 "PRIMARY KEY (time , latitude, longitude));")
            conn.exec_driver_sql(query_create_hypertable)

        with engine.connect() as conn, conn.begin():
            conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS ecmwf_neu_eu( "
                                 "time timestamp without time zone NOT NULL, "
                                 "temp_air double precision, "
                                 "ghi double precision, "
                                 "wind_meridional double precision, "
                                 "wind_zonal double precision, "
                                 "wind_speed double precision, "
                                 "precipitation double precision, "
                                 "latitude double precision, "
                                 "longitude double precision, "
                                 "nuts_id text, "
                                 "PRIMARY KEY (time , latitude, longitude, nuts_id));")
            conn.exec_driver_sql(query_create_hypertable_eu)
        log.info(f'created hypertable ecmwf')
    except Exception as e:
        log.error(f'could not create hypertable: {e}')


def save_data(request):
    request['area'] = coords
    # path for downloaded files from copernicus
    save_downloaded_files_path = os.path.realpath(os.path.join(os.path.dirname(__file__),
                                                               f'{request.get("year")}_{request.get("month")}_{request.get("day")[0]}-{request.get("month")}_{request.get("day")[len(request.get("day")) - 1]}_ecmwf.grb'))
    c.retrieve('reanalysis-era5-land', request, save_downloaded_files_path)


def get_wind_speed(row):
    return (row.wind_meridional ** 2) + (row.wind_zonal ** 2) ** 0.5


def psql_insert_copy(table, conn, keys, data_iter):
    # gets a DBAPI connection that can provide a cursor
    dbapi_conn = conn.connection
    with dbapi_conn.cursor() as cur:
        s_buf = StringIO()
        writer = csv.writer(s_buf)
        writer.writerows(data_iter)
        s_buf.seek(0)

        columns = ', '.join('"{}"'.format(k) for k in keys)
        if table.schema:
            table_name = '{}.{}'.format(table.schema, table.name)
        else:
            table_name = table.name

        sql = 'COPY {} ({}) FROM STDIN WITH CSV'.format(
            table_name, columns)
        cur.copy_expert(sql=sql, file=s_buf)


def build_dataframe(engine, request):
    file_path = os.path.realpath(os.path.join(os.path.dirname(__file__),
                                              f'{request.get("year")}_{request.get("month")}_{request.get("day")[0]}-{request.get("month")}_{request.get("day")[len(request.get("day")) - 1]}_ecmwf.grb'))
    weather_data = xr.open_dataset(file_path, engine="cfgrib")
    log.info(f'successfully read file {file_path}')
    weather_data = weather_data.to_dataframe()
    weather_data = weather_data.dropna(axis=0)
    weather_data = weather_data.reset_index()
    weather_data = weather_data.drop(['time', 'step', 'number', 'surface'], axis='columns')
    weather_data = weather_data.rename(
        columns={'valid_time': 'time', 'u10': 'wind_zonal', 'v10': 'wind_meridional', 't2m': 'temp_air', 'ssr': 'ghi',
                 'tp': 'precipitation'})
    weather_data["wind_speed"] = weather_data.apply(get_wind_speed, axis=1)
    weather_data = weather_data.round({'latitude': 2, 'longitude': 2})
    weather_data = weather_data.set_index(['time', 'latitude', 'longitude'])
    log.info('preparing to write dataframe into ecmwf database')
    weather_data.to_sql('ecmwf_neu', con=engine, if_exists='append', chunksize=10000, method=psql_insert_copy)

    nuts3 = gpd.GeoDataFrame.from_file(nuts_path)
    weather_data = weather_data.reset_index()
    weather_data['coords'] = list(zip(weather_data['longitude'], weather_data['latitude']))
    weather_data['coords'] = weather_data['coords'].apply(Point)
    weather_data = gpd.GeoDataFrame(weather_data, geometry='coords', crs=nuts3.crs)
    weather_data = gpd.sjoin(weather_data, nuts3, predicate="within", how='left')
    weather_data = pd.DataFrame(weather_data)
    weather_data = weather_data.loc[:,
                   ['time', 'latitude', 'longitude', 'wind_meridional', 'wind_zonal', 'wind_speed', 'temp_air', 'ghi',
                    'precipitation', 'NUTS_ID']]
    weather_data = weather_data.rename(columns={'NUTS_ID': 'nuts_id'})
    weather_data = weather_data.dropna(axis=0)
    weather_data = weather_data.groupby(['time', 'nuts_id']).mean()
    weather_data = weather_data.reset_index()
    weather_data = weather_data.set_index(['time', 'latitude', 'longitude', 'nuts_id'])
    log.info('preparing to write nuts dataframe into ecmwf_eu database')
    weather_data.to_sql('ecmwf_neu_eu', con=engine, if_exists='append', chunksize=10000, method=psql_insert_copy)

    # Delete file locally to save space
    try:
        os.remove(file_path)
    except OSError as e:
        log.info(f'Error: {e.filename} - {e.strerror}')


def get_latest_date_in_database(engine):
    day = default_start_date
    today = datetime.combine(date.today(), datetime.min.time())
    sql = text(f"select time from ecmwf_neu where time > '{day}' and time < '{today}' order by time desc limit 1")
    try:
        with engine.connect() as conn, conn.begin():
            last_date = pd.read_sql(sql, con=conn, parse_dates=['time']).values[0][0]
        last_date = pd.to_datetime(str(last_date))
        last_date = pd.to_datetime(last_date.strftime('%Y-%m-%d %H:%M:%S'))
        log.info(f'Last date in database is: {last_date}')
        return last_date
    except Exception as e:
        log.error(e)
        return default_start_date


def daterange(start_date):
    for n in range(int((datetime.combine(date.today(), datetime.min.time()) - start_date).days)):
        yield start_date + timedelta(n)


def request_builder(dates):
    dates_dataframe = pd.DataFrame(dates, columns=['Date'])
    g = dates_dataframe.groupby(pd.Grouper(key='Date', freq='M'))
    dfs = [group for _, group in g]
    for month in dfs:
        days = []
        for i in range(month.index.start, month.index.stop):
            days.append(f'{month["Date"].dt.day[i]:02d}')
        day_chunks = divide_month_in_chunks(days, 8)
        for chunk in day_chunks:
            request = dict(format='grib', variable=var_,
                           year=f'{month["Date"].dt.year[month.index.start]}',
                           month=f'{month["Date"].dt.month[month.index.start]:02d}',
                           day=chunk,
                           time=[f'{i:02d}:00' for i in range(24)])

            yield request


def divide_month_in_chunks(li, n):
    ch = []
    for i in range(0, len(li), n):
        ch.append(li[i:i + n])
    return ch


def main():
    engine = create_engine(db_uri)
    create_table(engine)
    last_date = get_latest_date_in_database(engine)
    dates = []
    for single_date in daterange(last_date):
        dates.append(single_date)
    for request in request_builder(dates):
        print(request)
        save_data(request)
        build_dataframe(engine, request)


if __name__ == '__main__':
    # db_uri = 'sqlite:///./data/weather.db'
    main()
    # engine = create_engine(db_uri)
    # build_dataframe(engine)
    # last_date = get_latest_date_in_database(engine)
    # dates = []
    # for single_date in daterange(last_date):
    #     dates.append(single_date)
    #
    # for request in request_builder(dates):
    #     print(request)
