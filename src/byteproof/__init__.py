"""byteproof —— 字节层缺陷取证引擎：给定工件，判「哪里不对」并给出规则依据。

本包为 Stage 1 新建的内核；旧包 ``errcode_atlas`` 在过渡期内并存，
器官（auditor）逐个迁入 ``byteproof.auditors`` 后再删除旧包。
"""

__version__ = "0.1.0.dev0"

__all__ = ["__version__"]