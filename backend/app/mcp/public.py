"""第三方只读 MCP。不注册报价草案、追踪维修等写工具。"""
from __future__ import annotations

import asyncio

from fastmcp import FastMCP
from loguru import logger

from app.mcp.access import PUBLIC_READ_TOOLS
from app.mcp import tools as mcp_tools

public_mcp = FastMCP("Car-Repair-Public")


async def _call(fn, timeout: float, *args, **kwargs):
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"[MCP-Public] 工具 {getattr(fn, '__name__', '?')} 执行超时（{timeout}s）")
        return "处理超时，请稍后再试。"


@public_mcp.tool()
async def query_work_order(work_order_no: str) -> str:
    """按工单号查询工单状态、车辆或设备和最新进度。只读。"""
    return await _call(mcp_tools.query_work_order, 10.0, work_order_no)


@public_mcp.tool()
async def query_compatible_parts(
    brand: str = "",
    series: str = "",
    year: int = 0,
    engine: str = "",
    plate: str = "",
    keyword: str = "",
) -> str:
    """按品牌、车系、年款、发动机或车牌查询适配备件和库存。只读。year 传 0 表示不限年款。"""
    return await _call(mcp_tools.query_compatible_parts, 10.0, brand, series, year, engine, plate, keyword)


@public_mcp.tool()
async def recommend_service(
    brand: str = "",
    series: str = "",
    mileage: int = -1,
    symptoms: str = "",
    plate: str = "",
) -> str:
    """按车型、里程和症状推荐保养套餐。只读。mileage 传 -1 表示未知里程。"""
    return await _call(mcp_tools.recommend_service, 10.0, brand, series, mileage, symptoms, plate)


@public_mcp.tool()
async def query_inventory(question: str) -> str:
    """按备件名称或编码查询库存。只读。"""
    return await _call(mcp_tools.query_inventory, 15.0, question)


@public_mcp.tool()
async def get_workorder_stats() -> str:
    """查询工单数量（总量、进行中、已完成）。只读，不是经营指标。"""
    return await _call(mcp_tools.get_workorder_stats, 10.0)


def public_http_app():
    return public_mcp.http_app(path="/", transport="streamable-http", stateless_http=True, json_response=True)


def public_tool_names() -> tuple:
    names = tuple(PUBLIC_READ_TOOLS)
    missing = [name for name in names if name not in {
        "query_work_order",
        "query_compatible_parts",
        "recommend_service",
        "query_inventory",
        "get_workorder_stats",
    }]
    if missing:
        raise RuntimeError(f"公开工具未实现: {missing}")
    return names
