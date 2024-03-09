import os

from nonebot import require
from nonebot.drivers import Driver
from tortoise import Tortoise

from zhenxun.models.goods_info import GoodsInfo
from zhenxun.models.sign_user import SignUser
from zhenxun.models.user_console import UserConsole
from zhenxun.services.log import logger
from zhenxun.utils.decorator.shop import shop_register

require("nonebot_plugin_apscheduler")
require("nonebot_plugin_alconna")
require("nonebot_plugin_session")
require("nonebot_plugin_saa")

from nonebot_plugin_saa import enable_auto_select_bot

enable_auto_select_bot()
from pathlib import Path

import nonebot
import ujson as json

path = Path(__file__).parent / "platform"
for d in os.listdir(path):
    nonebot.load_plugins(str((path / d).resolve()))


driver: Driver = nonebot.get_driver()

flag = True

SIGN_SQL = """
select distinct on("user_id") t1.user_id, t1.checkin_count, t1.add_probability, t1.specify_probability, t1.impression
from public.sign_group_users t1
  join ( 
    select user_id, max(t2.impression) as max_impression
    from public.sign_group_users t2
    group by user_id
  ) t on t.user_id = t1.user_id and t.max_impression = t1.impression
"""

BAG_SQL = """
select t1.user_id, t1.gold, t1.property
from public.bag_users t1
  join ( 
    select user_id, max(t2.gold) as max_gold
    from public.bag_users t2
    group by user_id
  ) t on t.user_id = t1.user_id and t.max_gold = t1.gold
"""


@driver.on_startup
async def _():
    global flag
    await shop_register.load_register()
    if (
        flag
        and not await UserConsole.annotate().count()
        and not await SignUser.annotate().count()
    ):
        flag = False
        db = Tortoise.get_connection("default")
        old_sign_list = await db.execute_query_dict(SIGN_SQL)
        old_bag_list = await db.execute_query_dict(BAG_SQL)
        goods = {
            g["goods_name"]: g["uuid"]
            for g in await GoodsInfo.annotate().values("goods_name", "uuid")
        }
        create_list = []
        sign_id_list = []
        uid = await UserConsole.get_new_uid()
        for old_sign in old_sign_list:
            sign_id_list.append(old_sign["user_id"])
            old_bag = [b for b in old_bag_list if b["user_id"] == old_sign["user_id"]]
            if old_bag:
                old_bag = old_bag[0]
                property = json.loads(old_bag["property"])
                props = {}
                if property:
                    for name, num in property.items():
                        if name in goods:
                            props[goods[name]] = num
                create_list.append(
                    UserConsole(
                        user_id=old_sign["user_id"],
                        platform="qq",
                        uid=uid,
                        props=props,
                        gold=old_bag["gold"],
                    )
                )
            else:
                create_list.append(
                    UserConsole(user_id=old_sign["user_id"], platform="qq", uid=uid)
                )
            uid += 1
        if create_list:
            logger.info("开始迁移用户数据...")
            await UserConsole.bulk_create(create_list, 10)
            logger.info("迁移用户数据完成!")
        create_list.clear()
        uc_dict = {u.user_id: u for u in await UserConsole.all()}
        for old_sign in old_sign_list:
            user_console = uc_dict.get(old_sign["user_id"])
            if not user_console:
                user_console = await UserConsole.get_user(old_sign["user_id"], "qq")
            create_list.append(
                SignUser(
                    user_id=old_sign["user_id"],
                    user_console=user_console,
                    platform="qq",
                    sign_count=old_sign["checkin_count"],
                    impression=old_sign["impression"],
                    add_probability=old_sign["add_probability"],
                    specify_probability=old_sign["specify_probability"],
                )
            )
        if create_list:
            logger.info("开始迁移签到数据...")
            await SignUser.bulk_create(create_list, 10)
            logger.info("迁移签到数据完成!")