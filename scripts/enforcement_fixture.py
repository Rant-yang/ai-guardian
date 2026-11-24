"""Synthetic decision injection for isolated CLI probes, never production startup."""
from unittest.mock import patch
import guardian.engine as engine

BLOCK_COMMAND='printf GUARDIAN_BLOCK_FIXTURE'


def enforcement_fixture():
    original=engine.assess
    def assess(tool,args):
        if tool in ('Bash','bash') and args.get('command')==BLOCK_COMMAND:
            return [dict(id='fixture_execution_gate',title='合成执行链验证',action='deny',
                         reason='隔离测试服务将无害打印动作设为拒绝，仅验证客户端是否落实决定。',
                         impact='不代表生产风险检测效果；即使钩子失效也只打印固定标记。')]
        return original(tool,args)
    return patch.object(engine,'assess',side_effect=assess)
