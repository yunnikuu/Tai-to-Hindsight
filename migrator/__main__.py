"""Source / packaged executable entry point."""
import argparse
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description='Tai → Hindsight 本地应用使用记录迁移')
    parser.add_argument('--demo',action='store_true',help='使用临时合成数据库演示')
    parser.add_argument('--self-test',metavar='REPORT_JSON',help='执行合成数据库端到端验证并写 JSON 报告')
    args=parser.parse_args()
    if args.self_test:
        from .demo import self_test
        return self_test(Path(args.self_test).resolve())
    from .gui import App
    App(demo=args.demo).mainloop()
    return 0

if __name__=='__main__': raise SystemExit(main())
