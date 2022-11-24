import time
import requests
import pandas as pd

import requests
import io
import zipfile

from crawler.base_crawler import BasicDbCrawler

import logging
from datetime import datetime, date, timedelta
import re

log = logging.getLogger('eview')
log.setLevel(logging.INFO)

default_start_date = date(2009,1,1)
# using http instead of https to be faster

class EViewCrawler(BasicDbCrawler):
    def get_solar_units(self):
        # crawl available pv units
        data = requests.get('http://www.eview.de/solarstromdaten/login.php')
        return re.findall('login\.php\?p=;(\w{2});', data.text)

    def crawl_unit_date(self, unit, fetch_date):
        with self.db_accessor() as connection:
            log.info(f'fetching {fetch_date} for {unit}')

            day = datetime.strftime(fetch_date,'%d.%m.%Y')
            url = f"http://www.eview.de/solarstromdaten/export.php?p=;{unit};z;dg1;f0;t{day}/1;km250"
            data = requests.get(url)
            df = pd.read_csv(url, decimal=',', index_col=0, encoding='iso-8859-1', skiprows=4, parse_dates=True)
            log.info(f'num records {df.size}')
            if df.size < 2:
                log.info('not data')
                return
            ddf = df.unstack()
            ddf = ddf.reset_index()
            ddf.index = ddf['Datum und Uhrzeit']
            ddf.index.name = 'datetime'
            del ddf['Datum und Uhrzeit']
            ddf.columns = ['plant', 'value']
            ddf['plant_id'] = unit
            ddf.to_sql('eview', con=connection, if_exists='append')

    def crawl_unit(self, unit, begin_date):
        first_date = pd.to_datetime(begin_date)+timedelta(days=1)
        last_date = date.today()-timedelta(days=1)
        for fetch_date in pd.date_range(first_date, last_date):
            self.crawl_unit_date(unit, fetch_date)

    def select_latest(self,unit):
        sql = f"select datetime from eview where plant_id='{unit}' order by datetime desc limit 1"
        with self.db_accessor() as connection:
            try:
                return pd.read_sql(sql,connection, parse_dates=['datetime']).values[0][0]
            except Exception as e:
                log.error(e)
                return default_start_date

    def create_hypertable(self):
        try:
            query_create_hypertable = "SELECT create_hypertable('eview', 'datetime', if_not_exists => TRUE, migrate_data => TRUE);"
            with self.db_accessor() as conn:
                conn.execute(query_create_hypertable)
            log.info(f'created hypertable eview')
        except Exception as e:
            log.error(f'could not create hypertable: {e}')

def main(db_uri):
    ec = EViewCrawler(db_uri)
    solar_plants = ec.get_solar_units()

    for plant in solar_plants:
        try:
            begin_date = ec.select_latest(plant)
            ec.crawl_unit(plant,begin_date)
        except Exception as e:
            log.exception(f'Error with {plant}')

    ec.create_hypertable()

if __name__ == '__main__':
    logging.basicConfig()

    db_uri = 'sqlite:///./data/eview.db'
    log.info(f'connect to {db_uri}')
    ec = EViewCrawler(db_uri)

    #main(db_uri)