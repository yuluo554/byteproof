"""器官 ``crsscope``：空间参考语义审计账本（迁自 target-map ② 行）。

回答三个问题：这批坐标是哪个坐标系（decl 声明-内容一致性五项）、会不会整体偏几百米
（detect 三假设评分 + 三段残差）、有没有混用（xdiff 跨实现差分 / geojson RFC 7946
结构 / tiles 瓦片轴序）。判定核逐字移植（两套 out_of_china 边界不合并——差异本身就是
审计发现点）；文件读取与报告渲染留输入层。逐条处置见 ``docs/crsscope.md`` §6。
"""

from __future__ import annotations

from byteproof.core.registry import Pack, register

from . import audit, spec

ORGAN_VERSION = spec.ORGAN_VERSION

PACK = register(
    Pack(
        slug="crsscope",
        version=ORGAN_VERSION,
        summary="空间参考账本：声明-内容一致性五项 + GCJ-02/BD-09 假设评分与三段残差 + 跨实现差分 + RFC 7946 结构七项 + 瓦片轴序五项",
        input_fields=("mode",),
        evaluate=audit.evaluate,
    )
)
