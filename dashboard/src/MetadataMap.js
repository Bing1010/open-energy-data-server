import React, { useState, useEffect, useRef } from 'react';
import { MapContainer, TileLayer, Marker, useMapEvents, ZoomControl } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import * as turf from '@turf/turf';
import L from 'leaflet';

import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';

function MapComponent({ metadataOptions, selectedMetadata }) {
    const position = [50.775132, 6.083861]; 
    const [clickedLocation, setClickedLocation] = useState(null);
    const [overlappingSources, setOverlappingSources] = useState([]);
    const [activeMetadata, setActiveMetadata] = useState([]);
    const mapRef = useRef(null);
    const geoJsonLayersRef = useRef([]);

    let DefaultIcon = L.icon({
        iconUrl: icon,
        shadowUrl: iconShadow,
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        tooltipAnchor: [16, -28],
        shadowSize: [41, 41]
    });

    L.Marker.prototype.options.icon = DefaultIcon;

    useEffect(() => {
        setActiveMetadata(selectedMetadata && selectedMetadata.concave_hull_geometry ? [selectedMetadata] : metadataOptions);
    }, [metadataOptions, selectedMetadata]);

    useEffect(() => {
        if (mapRef.current) {
            geoJsonLayersRef.current.forEach(layer => mapRef.current.removeLayer(layer));
            geoJsonLayersRef.current = [];

            activeMetadata.forEach(option => {
                const geoJsonLayer = L.geoJSON(option.concave_hull_geometry, {
                    style: {
                        color: 'rgb(255, 0, 0)',
                        weight: 0,
                        fillColor: 'rgb(255, 0, 0)',
                        fillOpacity: 0.2
                    }
                }).addTo(mapRef.current);
                geoJsonLayersRef.current.push(geoJsonLayer);
            });
        }
    }, [activeMetadata]);

    const MapEvents = () => {
        useMapEvents({
            click: (e) => {
                const clickedPoint = turf.point([e.latlng.lng, e.latlng.lat]);
                const overlaps = activeMetadata.filter((option) => {
                    if (option.concave_hull_geometry) {
                        const polygon = turf.polygon(option.concave_hull_geometry.coordinates);
                        return turf.booleanPointInPolygon(clickedPoint, polygon);
                    }
                    return false;
                });

                setClickedLocation(e.latlng);
                setOverlappingSources(overlaps);
            }
        });
        return null;
    };

    return (
        <div className="section">
            <h3>Availability Map</h3>
            <div className="chart-container">
                <MapContainer ref={mapRef} zoomControl={false} center={position} zoom={4} style={{ height: '600px', width: '60%' }}>
                    <TileLayer
                        url="https://map.nowum.fh-aachen.de/cartodb/light_all/{z}/{x}/{y}.png"
                        attribution='&copy; <a href="http://osm.org/copyright">OpenStreetMap</a> contributors'
                    />
                    <ZoomControl position='bottomleft' />
                    <MapEvents />
                    {clickedLocation && (
                        <Marker position={clickedLocation}></Marker>
                    )}
                </MapContainer>
            </div>
            <div className="details-container">
                <h4>Overlapping Sources at Click:</h4>
                <ul style={{ listStyleType: 'none' }}>
                    {overlappingSources.map((source, index) => (
                        <li key={index}>{source.schema_name || "Unnamed Source"}</li>
                    ))}
                </ul>
            </div>
        </div>
    );
}

export default MapComponent;
