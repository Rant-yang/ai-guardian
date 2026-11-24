"""Offline maintenance: no model calls, service startup, or arbitrary hook execution."""
import argparse
import json
import platform
import sys
import secrets
from datetime import datetime, timezone
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from . import adapter_registry
from .onboarding import Onboarding


def support_report(home=None):
    """Allowlisted diagnostic facts, never logs, event data or config contents."""
    from .runtime_revision import source_revision
    dependencies={}
    for name in ('pywebview','pythonnet','clr_loader'):
        try:dependencies[name]=version(name)
        except PackageNotFoundError:dependencies[name]='missing'
    return dict(schema='guardian-support-v1',created_at=datetime.now(timezone.utc).isoformat(),
        source_revision=source_revision(Path(__file__).parent),
        system=platform.system(),python='.'.join(map(str,sys.version_info[:3])),
        dependencies=dependencies,execution_verified=False,
        clients=[dict(id=row['id'],configuration=row['configuration']) for row in inspect(home)])


def export_report(root,home=None):
    from .config_files import check_path
    directory=Path(root)/'.local'/'support'
    check_path(directory);directory.mkdir(parents=True,exist_ok=True)
    target=directory/('report-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4)+'.json')
    check_path(target)
    with target.open('x',encoding='utf-8') as stream:
        json.dump(support_report(home),stream,ensure_ascii=False,indent=2)
    return target


def inspect(home=None):
    flow=Onboarding(home)
    rows=[]
    for client,name in adapter_registry.supported().items():
        try:
            state=flow.operation(client,'status')
            report=adapter_registry.preflight(client,state)
            rows.append(dict(id=client,name=name,**report))
        except Exception:
            # Exception text can contain private configuration or credentials.
            rows.append(dict(id=client,name=name,configuration='unreadable',
                             execution_verified=False,warnings=['配置无法读取；未执行或修改任何 Hook。']))
    return rows


def prepare_disconnect(flow):
    """Keep per-client conflicts separate; each plan still binds a file fingerprint."""
    plans=[];blocked=[]
    for client in adapter_registry.supported():
        try:
            plan=flow.preview([client],'uninstall')
            plans.append(plan)
        except Exception:
            blocked.append(client)
    return plans,blocked


def disconnect(flow,plans):
    results=[]
    for plan in plans:
        try:results.extend(flow.apply(plan['plan_id'],True)['results'])
        except Exception:
            results.append(dict(id=plan['clients'][0]['id'],state='failed',
                                message='计划已失效或配置发生变化；未按旧计划继续操作，请重新预览。'))
    return results


def main():
    parser=argparse.ArgumentParser(description='Guardian 离线维护（不启动后台）')
    parser.add_argument('action',choices=('check','disconnect','report'))
    args=parser.parse_args()
    if args.action=='report':
        path=export_report(Path(__file__).resolve().parents[1])
        print('诊断报告已保存：'+str(path))
        print('仅包含程序版本、依赖版本和接入状态；不包含令牌、配置内容、日志、用户名、文件路径或对话。请查看后自行发送给维护者；程序不会上传。')
        return
    if args.action=='check':
        labels={'configured':'配置存在，真实接入仍需验证','not_configured':'未配置',
                'attention':'需要核对旧版本或配置冲突','unreadable':'配置不可读取'}
        for row in inspect():
            print(row['name']+'：'+labels[row['configuration']])
            for warning in row['warnings']:print('  '+warning)
        print('\n诊断仅检查配置，不证明客户端已加载、后台在线或动作受到保护。')
        print('桌面无法启动：重新运行 Install.cmd；详细启动错误在 .local/launcher-error.log，请勿直接公开整个 .local。')
        return
    print('请先保存任务并退出已接入的 Agent。此操作撤销本目录拥有的接入，不删除模型、API、聊天记录或项目数据。')
    flow=Onboarding(Path.home());plans,blocked=prepare_disconnect(flow)
    for plan in plans:
        row=plan['clients'][0]
        print(row['name']+'：'+row['change']+'\n  '+row['path'])
    if blocked:print('以下客户端有冲突，保持原样：'+', '.join(blocked))
    try:answer=input('\n输入 REMOVE 确认以上变更，其他输入取消：').strip()
    except (EOFError,KeyboardInterrupt):print('\n已取消。');return
    if answer!='REMOVE':print('已取消，配置未修改。');return
    results=disconnect(flow,plans)
    for row in results:print(row['id']+'：'+row['message'])
    incomplete=blocked+[r['id'] for r in results if r['state'] in ('failed','uncertain')]
    if incomplete:
        print('撤销未全部完成，请保留本项目目录，处理以上冲突后重试。')
        raise SystemExit(1)
    print('当前检查范围内的接入已撤销。重新启动 Agent 后验证普通读写。')
    print('请关闭 Guardian 窗口，再运行 scripts/stop-background.ps1 正常停止后台。')
    print('本地记录和备份仍保留；确认不再需要后再处理项目目录。项目级或其他安装位置的接入不在本次范围内。')


if __name__=='__main__':main()
