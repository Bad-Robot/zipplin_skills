# 行程数据规范

JSON 顶层必须包含 `title` 和非空 `days`。推荐字段如下：

```json
{
  "title": "呼伦贝尔 8 天 7 晚",
  "subtitle": "草原、林海与边境村落环线",
  "region": "内蒙古自治区呼伦贝尔市",
  "date_range": "2026-10-01 — 2026-10-08",
  "transport": "driving",
  "coordinate_system": "GCJ-02",
  "route_provider": "高德地图 Web 服务",
  "route_queried_at": "2026-09-13",
  "days": [
    {
      "day": 1,
      "date": "10月1日",
      "title": "抵达草原门户",
      "summary": "机场取车后进入海拉尔市区",
      "stops": [
        {
          "name": "海拉尔东山机场",
          "address": "内蒙古自治区呼伦贝尔市海拉尔区机场大街",
          "lng": 119.824,
          "lat": 49.209,
          "time": "14:00",
          "activity": "取车",
          "note": "检查油量与轮胎",
          "motif": "grassland",
          "scenery": "草原门户"
        }
      ],
      "legs": [
        {
          "from": "海拉尔东山机场",
          "to": "海拉尔市区",
          "distance_km": 8.6,
          "duration_min": 18,
          "source": "amap",
          "polyline": [[119.824, 49.209], [119.76, 49.215]]
        }
      ],
      "lodging": {
        "name": "酒店名称",
        "address": "完整地址",
        "lng": 119.75,
        "lat": 49.21,
        "note": "连住 1 晚"
      },
      "meals": ["手把肉", "锅茶"],
      "tips": ["节假日提前加油"],
      "gallery": [
        {
          "title": "草原日落",
          "caption": "景点实景照片",
          "kind": "photo",
          "image": "images/sunset.png",
          "source_url": "https://原始来源页面",
          "author": "摄影者",
          "license": "实际使用许可"
        }
      ]
    }
  ]
}
```

## 必填与补全

- 每天至少两个 `stops` 才会产生路线段；只有一个地点时仍可生成日程卡片。
- `name` 必填。`address`、`lng`、`lat` 缺失时，脚本可用高德 Key 搜索补全。
- `legs` 可省略。脚本根据相邻 stops 调用驾车规划。已有 legs 时，数量应为 `len(stops)-1`，每段应包含 polyline、公里数和时间。
- 公共交通可把 `transport` 改为 `transit`，但当前构建脚本只自动请求驾车路线；其他交通方式应由调用者写入已核实的 legs。
- `lodging` 可以只写 `name` 和 `address`；若缺少坐标，优先匹配当天同名 stop，否则用高德补全。
- `motif` 支持 `grassland`、`river`、`forest`、`lake`、`village`、`wildlife`、`train`、`mountain`、`city`、`architecture`。未知值使用通用山水意象。
- `scenery_image` 放在 stop 中时会出现在地图景物卡；`gallery[].image` 只进入每日图片组。相对路径相对于输入 JSON 文件。

## 文字转 JSON 的约束

- 保留原行程顺序和用户明确指定的酒店、车站、景区入口。
- “额尔古纳”“根河”等行政区名必须落实为可导航的具体停靠点，并在 `note` 中注明选点假设。
- 环线首尾重复地点应分别出现在相应日期，以便生成最后一段道路。
- 距离以道路服务结果为准；不要从地图直线距离推导正式公里数。


## 正式输出新增字段

`gallery` 默认仅收录实景照片。插画应放在 stop 的 `scenery_image`，不能放入正式图集。每项：

```json
{"title":"景点实景", "kind":"photo", "image":"photos/spot.jpg", "caption":"拍摄季节或视角", "source_url":"https://来源页面", "author":"摄影者", "license":"许可或使用依据", "license_url":"https://许可说明"}
```

`source_url` 指向原始页面，不能只写图片 CDN 链接；无法查到作者时如实写“未署名”，不得杜撰。无法确定使用依据时继续找其他素材。下载并核实实景照片后以本地路径输入，生成器将其内联。`kind:photo` 是经人工视觉核实后的声明，脚本不能识别一张栅格图是否真实摄影。

每日可提供 `basemap`，否则有 Key 时自动抓取：

```json
{"image":"maps/day-1.png", "center":[121.59,38.89], "zoom":12, "width":1024, "height":768, "scale":2, "tile_size":512, "coordinate_system":"GCJ-02", "source":"© 高德地图", "queried_at":"2026-09-13"}
```

width/height 是请求的逻辑像素尺寸，非下载图片像素尺寸。不得从图片尺寸反推覆盖范围。当前页面使用 4:3 底图。输出 `day_maps` 由构建器重新生成，`map-day-N.svg` 用于逐日复核；`map.svg` 为第一天。`has_preview_basemaps` 表示缺少真实底图。
