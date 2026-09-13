#!/usr/bin/env python3
"""Offline smoke test for itinerary-visualizer."""

import json
import os
import base64
import basemap
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> None:
    os.environ.pop('AMAP_WEB_KEY', None)
    os.environ.pop('AMAP_KEY', None)
    root = Path(__file__).resolve().parents[1]
    script = root / "scripts" / "build_itinerary.py"
    fixture = root / "assets" / "example-itinerary.json"
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "site"
        result = subprocess.run(
            [sys.executable, str(script), "--input", str(fixture), "--output", str(output), "--require-real-route"],
            check=True,
            capture_output=True,
            text=True,
        )
        html = (output / "index.html").read_text(encoding="utf-8")
        svg = (output / "map.svg").read_text(encoding="utf-8")
        resolved = json.loads((output / "itinerary.resolved.json").read_text(encoding="utf-8"))
        assert "山海之间 2 日自驾" in html
        assert 'data-days="1"' in svg and 'data-days="2"' in (output / "map-day-2.svg").read_text()
        assert "42.8 km" in "".join(resolved["day_maps"].values()) and "79.6 km" in "".join(resolved["day_maps"].values())
        assert "lodging-node" in svg
        assert not resolved["has_preview_routes"]
        assert all(leg["source"] != "preview-estimate" for day in resolved["days"] for leg in day["legs"])
        assert resolved["total_distance_km"] == 186.0
        assert resolved["total_duration_min"] == 258
        assert "generated:" in result.stdout

        preview_data = json.loads(fixture.read_text(encoding="utf-8"))
        for day in preview_data["days"]:
            day.pop("legs", None)
        preview_input = Path(tmp) / "preview.json"
        preview_input.write_text(json.dumps(preview_data, ensure_ascii=False), encoding="utf-8")
        preview_output = Path(tmp) / "preview-site"
        subprocess.run(
            [sys.executable, str(script), "--input", str(preview_input), "--output", str(preview_output)],
            check=True,
            capture_output=True,
            text=True,
        )
        preview_resolved = json.loads((preview_output / "itinerary.resolved.json").read_text(encoding="utf-8"))
        assert preview_resolved["has_preview_routes"]
        rejected = subprocess.run(
            [sys.executable, str(script), "--input", str(preview_input), "--output", str(Path(tmp) / "rejected"), "--require-real-route"],
            capture_output=True,
            text=True,
        )
        assert rejected.returncode != 0
        assert "仍是预览估算" in rejected.stderr
        # Synthetic raster is strictly a software fixture, never a deliverable map/photo.
        raster = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5VQAAAAASUVORK5CYII='
        complete = json.loads(fixture.read_text())
        for day in complete['days']:
            day['basemap'] = dict(image=raster,center=[121,39],zoom=12,width=1024,height=768,tile_size=512,coordinate_system='GCJ-02',source='TEST FIXTURE')
            day['gallery'] = [dict(image=raster,kind='photo',title='TEST FIXTURE',source_url='https://example.org/photo',author='fixture',license='test only')]
        formal = Path(tmp)/'formal.json'
        def run_formal(payload):
            formal.write_text(json.dumps(payload))
            return subprocess.run([sys.executable,str(script),'--input',str(formal),'--output',str(Path(tmp)/'formal-site'),'--require-complete'],capture_output=True,text=True)
        assert run_formal(complete).returncode == 0
        result_data = json.loads((Path(tmp)/'formal-site/itinerary.resolved.json').read_text())
        assert len(result_data['day_maps']) == 2
        assert all('true-basemap' in svg and 'scale-bar' in svg for svg in result_data['day_maps'].values())
        del complete['days'][0]['basemap']
        assert '缺少真实地理底图' in run_formal(complete).stderr
        complete['days'][0]['basemap'] = complete['days'][1]['basemap'].copy()
        complete['days'][0]['gallery'][0]['image'] = 'data:image/svg+xml;base64,PHN2Zy8+'
        assert '不能用 SVG' in run_formal(complete).stderr
        complete['days'][0]['gallery'][0]['image'] = raster
        del complete['days'][0]['gallery'][0]['author']
        assert 'author' in run_formal(complete).stderr
        # Calibration invariant: a longitude delta equal to 1 logical pixel.
        meta = complete['days'][1]['basemap']
        project = basemap.projector(meta)
        assert project(121,39) == (600,450)
        delta = 360/(512*2**12)
        x,y = project(121+delta,39)
        assert abs(x-600-1200/1024)<1e-6 and abs(y-450)<1e-6
        meta['coordinate_system']='WGS84'
        try:
            basemap.validate(meta,'GCJ-02')
            raise AssertionError('mixed coordinates accepted')
        except ValueError:
            pass
    print("itinerary-visualizer offline smoke test: PASS")


if __name__ == "__main__":
    main()
