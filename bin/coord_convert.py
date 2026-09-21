#!/usr/bin/env python3
"""坐标系换算：GCJ-02（火星坐标，腾讯/高德/国内政府公示常用） <-> WGS-84（GPS/OSM）。

为什么需要它：
    itinerary.json 约定存 WGS-84。Photon/OSM/Wikipedia 给的直接就是 WGS-84；
    但腾讯地图、高德、百度、政府公示上的坐标通常是 GCJ-02（百度是 BD-09，偏差更大），
    直接把 GCJ-02 当 WGS-84 填进去，标记会偏 300~600m（云南实测约 350m）。

命令行用法：
    python3 coord_convert.py gcj2wgs 22.602054 101.097496   # -> 22.604820 101.095948
    python3 coord_convert.py wgs2gcj 22.604820 101.095948
    python3 coord_convert.py gcj2wgs --json 22.602054 101.097496

作为模块使用：
    from coord_convert import gcj_to_wgs, wgs_to_gcj
    lat, lng = gcj_to_wgs(22.602054, 101.097496)
"""
import argparse
import json
import math

A = 6378245.0  # 克拉索夫斯基椭球长半轴
EE = 0.00669342162296594323  # 偏心率平方


def _out_of_china(lng, lat):
    """中国大陆范围外不做偏移（GCJ-02 只在国内生效）。"""
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(x, y):
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x, y):
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs_to_gcj(lat, lng):
    """WGS-84 -> GCJ-02。境外坐标原样返回。"""
    if _out_of_china(lng, lat):
        return lat, lng
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = 1 - EE * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (A / sqrtmagic * math.cos(radlat) * math.pi)
    return lat + dlat, lng + dlng


def gcj_to_wgs(lat, lng):
    """GCJ-02 -> WGS-84。用二分法反解（正变换单调，迭代 60 次精度优于 1e-9 度）。"""
    if _out_of_china(lng, lat):
        return lat, lng
    lo_lat, hi_lat = lat - 0.01, lat + 0.01
    lo_lng, hi_lng = lng - 0.01, lng + 0.01
    for _ in range(60):
        m_lat = (lo_lat + hi_lat) / 2
        m_lng = (lo_lng + hi_lng) / 2
        g_lat, g_lng = wgs_to_gcj(m_lat, m_lng)
        if g_lat < lat:
            lo_lat = m_lat
        else:
            hi_lat = m_lat
        if g_lng < lng:
            lo_lng = m_lng
        else:
            hi_lng = m_lng
    return round((lo_lat + hi_lat) / 2, 6), round((lo_lng + hi_lng) / 2, 6)


def offset_meters(lat1, lng1, lat2, lng2):
    """两点近似距离（米），用于提示坐标系偏移量级。"""
    dy = (lat2 - lat1) * 111320.0
    dx = (lng2 - lng1) * 111320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dx, dy)


def main():
    ap = argparse.ArgumentParser(description="GCJ-02 <-> WGS-84 坐标换算")
    ap.add_argument("mode", choices=["gcj2wgs", "wgs2gcj"], help="换算方向")
    ap.add_argument("lat", type=float, help="纬度")
    ap.add_argument("lng", type=float, help="经度")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出（便于程序读取）")
    args = ap.parse_args()

    if args.mode == "gcj2wgs":
        out_lat, out_lng = gcj_to_wgs(args.lat, args.lng)
    else:
        out_lat, out_lng = wgs_to_gcj(args.lat, args.lng)

    shift = offset_meters(args.lat, args.lng, out_lat, out_lng)
    if args.json:
        print(json.dumps({"mode": args.mode, "lat": out_lat, "lng": out_lng,
                          "shift_m": round(shift)}, ensure_ascii=False))
    else:
        print(f"{out_lat:.6f} {out_lng:.6f}   （偏移 {shift:.0f} m）")


if __name__ == "__main__":
    main()
