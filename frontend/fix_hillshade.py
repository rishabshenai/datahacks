import re

with open('/Users/roycel/Downloads/UCSD/VS Code Stuff/404 Fish Now Found/datahacks/frontend/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

replacement = """                      map.on('load', () => {
                          // ADD HILLSHADE
                          map.addSource('terrarium', {
                              type: 'raster-dem',
                              tiles: ['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
                              encoding: 'terrarium',
                              tileSize: 256
                          });
                          map.setTerrain({ source: 'terrarium', exaggeration: 2.0 });

                          // STYLE LABELS WITH NEON HALOS
                          map.getStyle().layers.forEach(l => {
                              if(l.type === 'symbol' && l.layout && l.layout['text-field']) {
                                  map.setPaintProperty(l.id, 'text-halo-color', 'rgba(77, 168, 218, 0.5)');
                                  map.setPaintProperty(l.id, 'text-halo-width', 2);
                                  map.setPaintProperty(l.id, 'text-color', '#ffffff');
                              }
                          });

                          ZONES.forEach(zone => {"""

html = html.replace("                      map.on('load', () => {\n                          ZONES.forEach(zone => {", replacement)

with open('/Users/roycel/Downloads/UCSD/VS Code Stuff/404 Fish Now Found/datahacks/frontend/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
