"""本机维护者命令；连接串只从环境读取，网页没有角色授予接口。"""
import argparse
from studypilot.postgres import PostgresAuthStore
from studypilot.models import ValidationError
import sqlite3

def main():
    parser=argparse.ArgumentParser(description="管理 StudyPilot PostgreSQL 云端账号角色")
    parser.add_argument("action",choices=["grant-developer","revoke-developer"])
    parser.add_argument("username")
    args=parser.parse_args()
    try:
        auth=PostgresAuthStore()
        auth.set_role(args.username,"developer" if args.action=="grant-developer" else "user",confirmed=True)
    except (ValidationError,sqlite3.Error) as error:
        parser.exit(1,str(error)+"\n")
    print("云端账号角色已更新。")

if __name__=="__main__":
    main()
