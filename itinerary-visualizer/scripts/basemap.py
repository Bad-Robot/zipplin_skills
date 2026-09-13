"""Registered GCJ-02 AMap static basemaps. No key is serialized."""
import base64
import math
import time
import urllib.parse
import urllib.request


def world(lng, lat):
    return lng / 360 + .5, .5 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / (2 * math.pi)


def projector(meta, width=1200, height=900):
    cx, cy = world(*meta['center'])
    unit = meta['tile_size'] * 2 ** meta['zoom']
    def project(lng, lat):
        x, y = world(lng, lat)
        return ((x-cx)*unit+meta['width']/2)*width/meta['width'], ((y-cy)*unit+meta['height']/2)*height/meta['height']
    return project


def fetch(day, client):
    points = [world(s['lng'], s['lat']) for s in day['stops']]
    points += [world(*p) for leg in day['legs'] for p in leg['polyline']]
    hotel = day.get('lodging') or {}
    if hotel.get('lng') is not None:
        points.append(world(hotel['lng'], hotel['lat']))
    if not points:
        raise ValueError('底图缺少地点坐标')
    xs, ys = zip(*points)
    cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
    center = [round((cx-.5)*360, 6), round(math.degrees(2*math.atan(math.exp((.5-cy)*2*math.pi))-math.pi/2), 6)]
    # AMap v3/staticmap uses 512 logical pixels per tile at scale=2.
    # Returned raster doubles requested dimensions; do not double overlay coordinates.
    zoom = max(1, min(16, math.floor(math.log2(min(754/max(max(xs)-min(xs),1e-8),543/max(max(ys)-min(ys),1e-8))/512))))
    meta = dict(center=center, zoom=zoom, width=1024, height=768, tile_size=512,
                scale=2, coordinate_system='GCJ-02', source='© 高德地图', queried_at=time.strftime('%Y-%m-%d'))
    query = urllib.parse.urlencode(dict(key=client.key, location=','.join(map(str,center)), zoom=zoom, size='1024*768', scale=2))
    try:
        with urllib.request.urlopen('https://restapi.amap.com/v3/staticmap?'+query, timeout=45) as r:
            raw = r.read()
        if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('not a PNG')
    except Exception:
        raise RuntimeError('高德底图请求失败；检查 Key 权限、配额和网络（请求地址已隐藏）') from None
    meta['image'] = 'data:image/png;base64,' + base64.b64encode(raw).decode()
    time.sleep(1.1)
    return meta


def validate(meta, coordinate_system):
    if meta.get('coordinate_system') != coordinate_system:
        raise ValueError('底图与路线坐标系不一致')
    if not str(meta.get('image','')).startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')):
        raise ValueError('底图必须嵌入本地栅格图片')
    if not meta.get('source'):
        raise ValueError('底图缺少 source 署名')
    if len(meta.get('center',[])) != 2 or not all(math.isfinite(float(v)) for v in meta['center']):
        raise ValueError('底图中心无效')
    for field in ('width','height','tile_size','zoom'):
        if not isinstance(meta.get(field),(int,float)) or not math.isfinite(meta[field]) or meta[field] <= 0:
            raise ValueError('底图参数无效：'+field)
    if abs(meta['width']/meta['height']-4/3) > .001:
        raise ValueError('底图请求尺寸必须为 4:3，避免拉伸地理轮廓')
