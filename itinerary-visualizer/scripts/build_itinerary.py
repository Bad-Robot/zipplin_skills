#!/usr/bin/env python3
"""Build a standalone, hand-drawn itinerary map page from normalized JSON."""

from __future__ import annotations

import argparse
import basemap
import base64
import copy
import datetime as dt
import html
import json
import math
import mimetypes
import os
from pathlib import Path
import urllib.parse
import urllib.request

VIEW_W = 1200
VIEW_H = 900
PAD_X = 88
PAD_Y = 92
DAY_COLORS = ["#C45C38", "#3B7C78", "#8B6743", "#667C4E", "#8B5C75", "#B57939", "#3E6F91", "#765F9B"]


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lng1, lat1 = map(math.radians, a)
    lng2, lat2 = map(math.radians, b)
    d_lng, d_lat = lng2 - lng1, lat2 - lat1
    value = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(value)))


class AmapClient:
    def __init__(self, key: str):
        self.key = key

    def api(self, endpoint: str, **params: object) -> dict:
        params["key"] = self.key
        query = urllib.parse.urlencode(params)
        req = urllib.request.Request(
            f"https://restapi.amap.com/{endpoint}?{query}",
            headers={"User-Agent": "itinerary-visualizer/1.0"},
        )
        with urllib.request.urlopen(req, timeout=45) as response:
            data = json.load(response)
        if data.get("status") != "1":
            raise RuntimeError(f"高德接口失败：{data.get('info')} ({data.get('infocode')})")
        return data

    def resolve_place(self, query: str, region: str = "") -> dict:
        result = self.api(
            "v3/place/text",
            keywords=query,
            city=region,
            citylimit="false",
            offset=10,
            page=1,
            extensions="base",
        )
        pois = result.get("pois") or []
        if pois:
            poi = pois[0]
            location = poi.get("entr_location") or poi.get("location")
            if location:
                lng, lat = map(float, location.split(","))
                address = "".join(
                    str(poi.get(field) or "")
                    for field in ("pname", "cityname", "adname", "address")
                )
                return {
                    "name": poi.get("name") or query,
                    "address": address,
                    "lng": lng,
                    "lat": lat,
                    "poi_id": poi.get("id", ""),
                    "coordinate_source": "entr_location" if poi.get("entr_location") else "location",
                }
        result = self.api("v3/geocode/geo", address=query, city=region)
        geocodes = result.get("geocodes") or []
        if not geocodes:
            raise RuntimeError(f"无法定位地点：{query}")
        item = geocodes[0]
        lng, lat = map(float, item["location"].split(","))
        return {
            "name": query,
            "address": item.get("formatted_address") or query,
            "lng": lng,
            "lat": lat,
            "coordinate_source": "geocode",
        }

    def driving(self, origin: tuple[float, float], destination: tuple[float, float]) -> dict:
        result = self.api(
            "v5/direction/driving",
            origin=f"{origin[0]},{origin[1]}",
            destination=f"{destination[0]},{destination[1]}",
            strategy=32,
            show_fields="cost,polyline",
        )
        paths = result.get("route", {}).get("paths") or []
        if not paths:
            raise RuntimeError("高德未返回可用驾车路线")
        path = paths[0]
        coordinates: list[list[float]] = []
        roads: list[str] = []
        for step in path.get("steps") or []:
            road = step.get("road_name")
            if road and road not in roads:
                roads.append(road)
            for pair in (step.get("polyline") or "").split(";"):
                if not pair:
                    continue
                point = [float(v) for v in pair.split(",")]
                if not coordinates or coordinates[-1] != point:
                    coordinates.append(point)
        return {
            "distance_km": round(float(path["distance"]) / 1000, 1),
            "duration_min": round(float((path.get("cost") or {}).get("duration") or 0) / 60),
            "polyline": coordinates,
            "roads": roads,
            "source": "amap",
        }


def ensure_number(value: object, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        fail(f"{label} 必须是数字")


def point(stop: dict) -> tuple[float, float]:
    return float(stop["lng"]), float(stop["lat"])


def normalize(data: dict, client: AmapClient | None, require_real: bool) -> dict:
    if not isinstance(data, dict) or not str(data.get("title") or "").strip():
        fail("顶层 title 不能为空")
    if not isinstance(data.get("days"), list) or not data["days"]:
        fail("顶层 days 必须是非空数组")

    result = copy.deepcopy(data)
    result.setdefault("coordinate_system", "GCJ-02")
    result.setdefault("route_provider", "高德地图 Web 服务" if client else "输入数据")
    result.setdefault("route_queried_at", dt.date.today().isoformat())
    region = str(result.get("region") or "")

    for day_index, day in enumerate(result["days"], start=1):
        if not isinstance(day, dict):
            fail(f"Day {day_index} 必须是对象")
        day.setdefault("day", day_index)
        day.setdefault("title", f"第 {day_index} 天")
        stops = day.get("stops") or []
        if not isinstance(stops, list):
            fail(f"Day {day_index} 的 stops 必须是数组")
        for stop_index, stop in enumerate(stops, start=1):
            if not isinstance(stop, dict) or not str(stop.get("name") or "").strip():
                fail(f"Day {day_index} stop {stop_index} 缺少 name")
            if stop.get("lng") is None or stop.get("lat") is None:
                if not client:
                    fail(f"地点“{stop['name']}”缺少坐标；请提供坐标或设置 AMAP_WEB_KEY")
                resolved = client.resolve_place(
                    str(stop.get("address") or stop["name"]),
                    str(stop.get("region") or region),
                )
                for key, value in resolved.items():
                    stop.setdefault(key, value)
            stop["lng"] = ensure_number(stop["lng"], f"{stop['name']}.lng")
            stop["lat"] = ensure_number(stop["lat"], f"{stop['name']}.lat")
            stop.setdefault("address", stop["name"])
            stop.setdefault("activity", "停靠与游览")

        lodging = day.get("lodging")
        if isinstance(lodging, dict) and lodging.get("name"):
            if lodging.get("lng") is None or lodging.get("lat") is None:
                matched = next((s for s in stops if s["name"] == lodging["name"]), None)
                if matched:
                    lodging.setdefault("lng", matched["lng"])
                    lodging.setdefault("lat", matched["lat"])
                    lodging.setdefault("address", matched.get("address", ""))
                elif client:
                    resolved = client.resolve_place(
                        str(lodging.get("address") or lodging["name"]),
                        str(lodging.get("region") or region),
                    )
                    for key, value in resolved.items():
                        lodging.setdefault(key, value)
                elif stops:
                    lodging.setdefault("lng", stops[-1]["lng"])
                    lodging.setdefault("lat", stops[-1]["lat"])
                    lodging.setdefault("coordinate_source", "last_stop_preview")
            if lodging.get("lng") is not None and lodging.get("lat") is not None:
                lodging["lng"] = ensure_number(lodging["lng"], f"{lodging['name']}.lng")
                lodging["lat"] = ensure_number(lodging["lat"], f"{lodging['name']}.lat")

        existing_legs = day.get("legs")
        expected = max(0, len(stops) - 1)
        if existing_legs is not None and len(existing_legs) != expected:
            fail(f"Day {day_index} 的 legs 数量应为 {expected}，实际为 {len(existing_legs)}")
        legs: list[dict] = []
        for leg_index in range(expected):
            origin, destination = stops[leg_index], stops[leg_index + 1]
            supplied = copy.deepcopy(existing_legs[leg_index]) if existing_legs is not None else None
            valid_supplied = supplied and supplied.get("polyline") and supplied.get("distance_km") is not None
            if valid_supplied:
                leg = supplied
                leg.setdefault("source", "provided")
            elif client:
                mode = (supplied or {}).get('transport') or day.get('transport') or result.get('transport', 'driving')
                if mode not in ('driving', 'taxi'):
                    fail('非驾车路段必须提供相应交通方式的已核实 polyline，不能用驾车替代')
                leg = client.driving(point(origin), point(destination))
            else:
                direct = haversine_km(point(origin), point(destination))
                preview_km = round(direct * 1.25, 1)
                leg = {
                    "distance_km": preview_km,
                    "duration_min": max(1, round(preview_km / 55 * 60)),
                    "polyline": [[origin["lng"], origin["lat"]], [destination["lng"], destination["lat"]]],
                    "source": "preview-estimate",
                    "roads": [],
                }
            leg["from"] = origin["name"]
            leg["to"] = destination["name"]
            leg["distance_km"] = ensure_number(leg["distance_km"], "distance_km")
            leg["duration_min"] = round(ensure_number(leg.get("duration_min", 0), "duration_min"))
            polyline = leg.get("polyline") or []
            if len(polyline) < 2:
                fail(f"Day {day_index} 路段 {leg_index + 1} 缺少有效 polyline")
            leg["polyline"] = [[ensure_number(p[0], "polyline.lng"), ensure_number(p[1], "polyline.lat")] for p in polyline]
            if require_real and leg.get("source") == "preview-estimate":
                fail(f"Day {day_index} 的 {leg['from']} → {leg['to']} 仍是预览估算，无法生成正式地图")
            legs.append(leg)
        day["legs"] = legs
        day["distance_km"] = round(sum(float(leg["distance_km"]) for leg in legs), 1)
        day["duration_min"] = round(sum(float(leg["duration_min"]) for leg in legs))
    result["total_distance_km"] = round(sum(day["distance_km"] for day in result["days"]), 1)
    result["total_duration_min"] = round(sum(day["duration_min"] for day in result["days"]))
    result["has_preview_routes"] = any(
        leg.get("source") == "preview-estimate"
        for day in result["days"]
        for leg in day["legs"]
    )
    return result


def embed_local_images(data: dict, input_dir: Path) -> None:
    def embed(value: object) -> object:
        if not isinstance(value, str) or not value or value.startswith(("data:", "http://", "https://")):
            return value
        candidate = (input_dir / value).resolve()
        if not candidate.is_file():
            return value
        mime = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    for day in data["days"]:
        if day.get("basemap", {}).get("image"):
            day["basemap"]["image"] = embed(day["basemap"]["image"])
        for stop in day.get("stops") or []:
            if stop.get("scenery_image"):
                stop["scenery_image"] = embed(stop["scenery_image"])
        for item in day.get("gallery") or []:
            if item.get("image"):
                item["image"] = embed(item["image"])


def mercator_y(lat: float) -> float:
    limited = max(-85, min(85, lat))
    rad = math.radians(limited)
    return math.log(math.tan(math.pi / 4 + rad / 2))


def make_projector(data: dict):
    coordinates: list[tuple[float, float]] = []
    for day in data["days"]:
        coordinates.extend(point(stop) for stop in day.get("stops") or [])
        lodging = day.get("lodging")
        if isinstance(lodging, dict) and lodging.get("lng") is not None:
            coordinates.append((float(lodging["lng"]), float(lodging["lat"])))
        for leg in day["legs"]:
            coordinates.extend((float(p[0]), float(p[1])) for p in leg["polyline"])
    if not coordinates:
        fail("没有可绘制的坐标")
    raw = [(math.radians(lng), mercator_y(lat)) for lng, lat in coordinates]
    min_x, max_x = min(p[0] for p in raw), max(p[0] for p in raw)
    min_y, max_y = min(p[1] for p in raw), max(p[1] for p in raw)
    if max_x - min_x < 1e-8:
        min_x -= 0.01
        max_x += 0.01
    if max_y - min_y < 1e-8:
        min_y -= 0.01
        max_y += 0.01
    scale = min((VIEW_W - 2 * PAD_X) / (max_x - min_x), (VIEW_H - 2 * PAD_Y) / (max_y - min_y))
    center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2

    def project(lng: float, lat: float) -> tuple[float, float]:
        x = VIEW_W / 2 + (math.radians(lng) - center_x) * scale
        y = VIEW_H / 2 - (mercator_y(lat) - center_y) * scale
        return x, y

    return project, (min(p[0] for p in coordinates), max(p[0] for p in coordinates), min(p[1] for p in coordinates), max(p[1] for p in coordinates))


def svg_path(polyline: list[list[float]], project) -> str:
    points = [project(float(p[0]), float(p[1])) for p in polyline]
    return "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in points)


def polyline_midpoint(polyline: list[list[float]], project) -> tuple[float, float]:
    points = [project(float(p[0]), float(p[1])) for p in polyline]
    lengths = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:])]
    target, walked = sum(lengths) / 2, 0.0
    for index, length in enumerate(lengths):
        if walked + length >= target:
            ratio = 0 if length == 0 else (target - walked) / length
            a, b = points[index], points[index + 1]
            return a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio
        walked += length
    return points[-1]


def motif_markup(motif: str, x: float, y: float, width: float, height: float) -> str:
    motif = motif or "mountain"
    base = [f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" fill="#FAF5E9" stroke="#D2CDB5"/>']
    if motif in {"forest", "wildlife", "train"}:
        for offset, size in ((18, 31), (43, 39), (70, 28), (94, 36)):
            base.append(f'<path d="M{x+offset} {y+height-17}l{size/3:.1f}-{size}l{size/3:.1f} {size}" fill="#78906A" stroke="#315B46" stroke-width="1.5"/>')
    elif motif in {"river", "lake"}:
        base.append(f'<path d="M{x+5} {y+height*.58} Q{x+width*.3} {y+height*.35} {x+width*.55} {y+height*.62} T{x+width-5} {y+height*.48} V{y+height-7} H{x+5}Z" fill="#91BCB8" opacity=".8"/>')
        base.append(f'<path d="M{x+15} {y+25} Q{x+35} {y+7} {x+55} {y+25} T{x+100} {y+23}" fill="none" stroke="#72866B" stroke-width="3"/>')
    elif motif in {"village", "architecture", "city"}:
        for offset, w, h in ((13, 31, 36), (47, 38, 48), (89, 24, 31)):
            base.append(f'<path d="M{x+offset} {y+height-14}v-{h}h{w}v{h}z" fill="#D6A96B" stroke="#79593B" stroke-width="2"/>')
            base.append(f'<path d="M{x+offset-4} {y+height-14-h}l{w/2+4}-{14}l{w/2+4} 14" fill="#B9603C" stroke="#79593B" stroke-width="2"/>')
    else:
        base.append(f'<circle cx="{x+width-24}" cy="{y+22}" r="12" fill="#E8B65D" opacity=".85"/>')
        base.append(f'<path d="M{x+5} {y+height-14} L{x+38} {y+27} L{x+64} {y+height-14} L{x+91} {y+39} L{x+width-5} {y+height-14}Z" fill="#91A47B" stroke="#526D58" stroke-width="2"/>')
    return "".join(base)


def build_map_svg(data: dict) -> str:
    project, bounds = make_projector(data)
    background = data.get('basemap')
    if background:
        project = basemap.projector(background, VIEW_W, VIEW_H)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{VIEW_W}" height="{VIEW_H}" viewBox="0 0 {VIEW_W} {VIEW_H}" role="img" aria-label="{esc(data["title"])} 行程地图">',
        '<defs><filter id="paper"><feTurbulence baseFrequency=".75" numOctaves="2" seed="7" type="fractalNoise"/><feColorMatrix values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 .055 0"/></filter><filter id="shadow"><feDropShadow dx="0" dy="3" stdDeviation="4" flood-opacity=".16"/></filter></defs>',
        '<rect width="1200" height="800" fill="#F7F1E5"/><rect width="1200" height="800" filter="url(#paper)" opacity=".6"/>',
        '<ellipse cx="930" cy="260" rx="320" ry="220" fill="#C7D5B0" opacity=".18"/><ellipse cx="320" cy="625" rx="390" ry="210" fill="#B5CFC3" opacity=".15"/>',
    ]
    if background:
        out = out[:2] + [
            '<defs><filter id="paper-tone"><feColorMatrix type="saturate" values=".38"/><feComponentTransfer><feFuncR type="linear" slope=".74" intercept=".25"/><feFuncG type="linear" slope=".77" intercept=".20"/><feFuncB type="linear" slope=".67" intercept=".23"/></feComponentTransfer></filter></defs>',
            f'<image class="true-basemap" href="{esc(background["image"])}" width="1200" height="900" filter="url(#paper-tone)"/><rect class="map-paper-grain" width="1200" height="900" filter="url(#paper)" pointer-events="none"/>']
        mpp = 40075016.686 * math.cos(math.radians(background['center'][1])) / (background['tile_size'] * 2 ** background['zoom']) * background['width'] / VIEW_W
        max_km = 130*mpp/1000
        km = 10 ** math.floor(math.log10(max_km))
        km *= max(v for v in (1,2,5) if v*km <= max_km)
        length = km*1000/mpp
        out.append(f'<g class="scale-bar"><rect x="25" y="820" width="260" height="65" rx="8" fill="#fffaf0"/><path d="M45 840h{length:.2f}m0-5v10M45 835v10" stroke="#31543d" fill="none"/><text x="45" y="870" font-size="13">{km:g} km · 中心纬度参考</text></g>')
        out.append(f'<text x="320" y="880" font-size="12" fill="#31543d" stroke="#fffaf0" stroke-width="3" paint-order="stroke">{esc(background["source"])} · {esc(background.get("queried_at", ""))} · {esc(data.get("coordinate_system"))}</text>')
    min_lng, max_lng, min_lat, max_lat = bounds
    for index in ([] if background else range(1, 5)):
        lng = min_lng + (max_lng - min_lng) * index / 5
        x, _ = project(lng, (min_lat + max_lat) / 2)
        out.append(f'<path d="M{x:.1f} 28V772" stroke="#87927D" stroke-opacity=".16" stroke-dasharray="3 8"/><text x="{x+5:.1f}" y="786" font-size="11" fill="#89917D">{lng:.1f}°E</text>')
        lat = min_lat + (max_lat - min_lat) * index / 5
        _, y = project((min_lng + max_lng) / 2, lat)
        out.append(f'<path d="M28 {y:.1f}H1172" stroke="#87927D" stroke-opacity=".16" stroke-dasharray="3 8"/><text x="31" y="{y-5:.1f}" font-size="11" fill="#89917D">{lat:.1f}°N</text>')

    scenery_candidates: list[tuple[int, dict]] = []
    seen_scenery: set[str] = set()
    for day in data["days"]:
        day_no = int(day["day"])
        for stop in day.get("stops") or []:
            if (stop.get("scenery") or stop.get("scenery_image")) and stop["name"] not in seen_scenery:
                seen_scenery.add(stop["name"])
                scenery_candidates.append((day_no, stop))
    card_slots = [(22, 34), (184, 26), (346, 34), (692, 26), (854, 34), (1016, 26)]
    for card_index, (day_no, stop) in enumerate(scenery_candidates[: len(card_slots)]):
        x, y = card_slots[card_index]
        px, py = project(float(stop["lng"]), float(stop["lat"]))
        out.append(f'<g class="geo scenery-node" data-days="{day_no}" opacity=".78"><path d="M{px:.1f},{py:.1f} L{x+76},{y+58}" stroke="#A99877" stroke-width="1.4" stroke-dasharray="4 5"/>')
        image = stop.get("scenery_image")
        if image:
            clip_id = f"scene-clip-{card_index}"
            out.append(f'<defs><clipPath id="{clip_id}"><rect x="{x}" y="{y}" width="150" height="105" rx="12"/></clipPath></defs><image href="{esc(image)}" x="{x}" y="{y}" width="150" height="105" preserveAspectRatio="xMidYMid slice" clip-path="url(#{clip_id})"/>')
            out.append(f'<rect x="{x}" y="{y}" width="150" height="105" rx="12" fill="none" stroke="#D2CDB5"/>')
        else:
            out.append(motif_markup(str(stop.get("motif") or "mountain"), x, y, 150, 105))
        out.append(f'<text x="{x+75}" y="{y+98}" text-anchor="middle" font-size="12" font-weight="700" fill="#294D3B" stroke="#FAF5E9" stroke-width="4" paint-order="stroke">{esc(stop.get("scenery") or stop["name"])}</text></g>')

    route_index = 0
    for day_offset, day in enumerate(data["days"]):
        day_no = int(day["day"])
        color = "#cb612d"
        for leg in day["legs"]:
            route_index += 1
            path = svg_path(leg["polyline"], project)
            dash = ' stroke-dasharray="7 6"' if leg.get('transport') == 'walking' else ''
            midpoint = polyline_midpoint(leg["polyline"], project)
            status = " · 预览" if leg.get("source") == "preview-estimate" else ""
            out.append(f'<g class="geo route-group" data-days="{day_no}" data-route="{route_index}"><title>{esc(leg["from"])} → {esc(leg["to"])} · {leg["distance_km"]:.1f} km{status}</title><path d="{path}" fill="none" stroke="#FFF9ED" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/><path class="route-path" d="{path}" fill="none" stroke="{color}" stroke-width="4.2" stroke-linecap="round" stroke-linejoin="round"{dash}/></g>')
            label = f'{leg["distance_km"]:.1f} km'
            pill_w = max(64, 15 + len(label) * 7)
            out.append(f'<g class="geo distance-label" data-days="{day_no}" transform="translate({midpoint[0]:.1f} {midpoint[1]-13:.1f})"><rect x="{-pill_w/2:.1f}" y="-12" width="{pill_w}" height="24" rx="12" fill="#FFFBF2" stroke="{color}"/><text y="4" text-anchor="middle" font-size="12" font-weight="700" fill="{color}">{label}</text></g>')

    grouped: dict[tuple[str, float, float], dict] = {}
    for day in data["days"]:
        for stop in day.get("stops") or []:
            key = (stop["name"], round(float(stop["lng"]), 6), round(float(stop["lat"]), 6))
            grouped.setdefault(key, {"stop": stop, "days": []})["days"].append(str(day["day"]))
    occupied = []
    for number, item in enumerate(grouped.values(), start=1):
        stop, days = item["stop"], " ".join(item["days"])
        x, y = project(float(stop["lng"]), float(stop["lat"]))
        label_width = min(400, len(stop['name'])*17)
        label_x = max(12,min(VIEW_W-label_width-12,x+16))
        label_y = max(120,min(790,y-20))
        for offset in (0,30,-30,60,-60,90,-90,120,-120):
            candidate_y = max(120,min(790,label_y+offset))
            box = (label_x,candidate_y-20,label_x+label_width,candidate_y+5)
            if all(box[2]<q[0] or box[0]>q[2] or box[3]<q[1] or box[1]>q[3] for q in occupied):
                label_y=candidate_y
                occupied.append(box)
                break
        anchor, dx = 'start', label_x-x
        out.append(f'<g class="geo stop-node map-point" data-name="{esc(stop["name"])}" tabindex="0" role="button" aria-label="{esc(stop["name"])}，查看行程" data-days="{days}"><title>{esc(stop["name"])} · {esc(stop.get("address", ""))}</title><circle cx="{x:.2f}" cy="{y:.2f}" r="11" fill="#315B46" stroke="#FFFBF2" stroke-width="3"/><text x="{x:.2f}" y="{y+4:.2f}" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">{number}</text><path d="M{x:.2f} {y:.2f}L{label_x:.2f} {label_y:.2f}" stroke="#315B46" stroke-opacity=".4" stroke-dasharray="3 3"/><text x="{x+dx:.2f}" y="{label_y:.2f}" text-anchor="{anchor}" font-size="17" font-weight="700" fill="#294D3B" stroke="#FFF9ED" stroke-width="5" paint-order="stroke">{esc(stop["name"])}</text></g>')

    for day in data["days"]:
        lodging = day.get("lodging")
        if not isinstance(lodging, dict) or lodging.get("lng") is None:
            continue
        x, y = project(float(lodging["lng"]), float(lodging["lat"]))
        out.append(f'<g class="geo lodging-node" data-days="{day["day"]}" transform="translate({x+14:.1f} {y+13:.1f})"><title>住宿：{esc(lodging["name"])}</title><path d="M0 0v16M0 10h24v6M5 5v5M5 5h9a5 5 0 0 1 5 5" fill="none" stroke="#2874A6" stroke-width="3" stroke-linecap="round"/><rect x="-6" y="-7" width="36" height="30" rx="8" fill="#F4FBFF" stroke="#2874A6" stroke-width="1.5" opacity=".24"/></g>')

    out.extend([
        '<g aria-label="指北针"><text x="1140" y="702" text-anchor="middle" font-size="17" font-weight="700" fill="#315B46">N</text><path d="M1140 762V714M1133 726l7-14 7 14" fill="none" stroke="#315B46" stroke-width="2.5"/></g>',
        f'<text x="36" y="767" font-size="12" fill="#7E8776">{esc(data.get("coordinate_system", "GCJ-02"))} · 地理位置按坐标投影 · 景物不按比例</text>',
        '</svg>',
    ])
    return "".join(out)


def safe_script_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def build(input_path: Path, output_dir: Path, require_real: bool, require_complete: bool = False) -> tuple[Path, dict]:
    try:
        raw = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"无法读取输入 JSON：{exc}")
    key = os.environ.get("AMAP_WEB_KEY") or os.environ.get("AMAP_KEY")
    client = AmapClient(key) if key else None
    resolved = normalize(raw, client, require_real or require_complete)
    embed_local_images(resolved, input_path.parent)
    maps = {}
    for day in resolved['days']:
        if not day.get('basemap') and client:
            if resolved['coordinate_system'] != 'GCJ-02':
                fail('高德底图只支持叠加 GCJ-02 数据')
            day['basemap'] = basemap.fetch(day, client)
        if day.get('basemap'):
            try:
                basemap.validate(day['basemap'], resolved['coordinate_system'])
            except ValueError as exc:
                fail(str(exc))
        elif require_complete:
            fail(f"Day {day['day']} 缺少真实地理底图；不能交付仅路线地图")
        if require_complete:
            if not day.get('gallery'):
                fail(f"Day {day['day']} 缺少实景照片；请搜索并核实素材")
            for photo in day['gallery']:
                if photo.get('kind') != 'photo' or not str(photo.get('image','')).startswith(('data:image/jpeg;base64,','data:image/png;base64,','data:image/webp;base64,')):
                    fail('正式图集只接受已嵌入的实景照片，不能用 SVG/插画替代')
                if not all(photo.get(k) for k in ('source_url','author','license')):
                    fail('实景照片必须记录 source_url、author、license')
        single = {**resolved, 'days':[day], 'basemap':day.get('basemap')}
        maps[str(day['day'])] = build_map_svg(single)
    resolved['has_preview_basemaps'] = any(not d.get('basemap') for d in resolved['days'])
    resolved['day_maps'] = maps
    svg = maps[str(resolved['days'][0]['day'])]

    skill_root = Path(__file__).resolve().parents[1]
    template_path = skill_root / "assets" / "itinerary-template.html"
    template = template_path.read_text(encoding="utf-8")
    document = (
        template.replace("__VISUAL_CSS__", (skill_root / "assets" / "itinerary-style.css").read_text(encoding="utf-8")).replace("__TITLE__", esc(resolved["title"]))
        .replace("__SUBTITLE__", esc(resolved.get("subtitle") or resolved.get("region") or "旅行路线手记"))
        .replace("__MAP_SVG__", svg)
        .replace("__ITINERARY_JSON__", safe_script_json(resolved))
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    for day_no, day_svg in maps.items():
        (output_dir / f'map-day-{day_no}.svg').write_text(day_svg, encoding='utf-8')
    html_path = output_dir / "index.html"
    html_path.write_text(document, encoding="utf-8")
    (output_dir / "map.svg").write_text(svg, encoding="utf-8")
    (output_dir / "itinerary.resolved.json").write_text(
        json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return html_path, resolved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="行程 JSON")
    parser.add_argument("--output", required=True, type=Path, help="输出目录")
    parser.add_argument("--require-real-route", action="store_true", help="拒绝直线估算路线")
    parser.add_argument("--require-complete", action="store_true", help="正式交付：要求真实路线、地理底图及有来源的实景照片")
    args = parser.parse_args()
    html_path, resolved = build(args.input.resolve(), args.output.resolve(), args.require_real_route, args.require_complete)
    print(f"generated: {html_path}")
    print(f"days: {len(resolved['days'])}, distance: {resolved['total_distance_km']:.1f} km")
    if resolved["has_preview_routes"]:
        print("warning: output contains preview-estimate routes")


if __name__ == "__main__":
    main()
