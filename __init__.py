from json import load, dump
from nonebot import get_bot
from hoshino import priv
from hoshino.typing import NoticeSession, MessageSegment
from .pcrclient import pcrclient, ApiException
from asyncio import Lock
from os.path import dirname, join, exists
from copy import deepcopy
from traceback import format_exc
from .safeservice import SafeService
from .playerpref import decryptxml
from .create_img import generate_info_pic, generate_support_pic, _get_cx_name
from hoshino.util import pic2b64
import time

sv_help = '''
注意：数字3为服务器编号，支持1、2、3或4
关键词之间可以留空格也可以不留

[竞技场绑定 3 uid] 绑定竞技场排名变动推送，默认双场均启用，仅排名降低时推送
[竞技场查询 3 uid] 查询竞技场简要信息（绑定后无需输入3 uid）
[停止竞技场订阅] 停止战斗竞技场排名变动推送
[停止公主竞技场订阅] 停止公主竞技场排名变动推送
[启用竞技场订阅] 启用战斗竞技场排名变动推送
[启用公主竞技场订阅] 启用公主竞技场排名变动推送
[删除竞技场订阅] 删除竞技场排名变动推送绑定
[竞技场订阅状态] 查看排名变动推送绑定状态
[详细查询 3 uid] 查询账号详细信息（绑定后无需输入3 uid）
[查询群数] 查询bot所在群的数目
[查询竞技场订阅数] 查询绑定账号的总数量
[清空竞技场订阅] 清空所有绑定的账号(仅限主人)
'''.strip()

sv = SafeService('竞技场推送_tw', help_=sv_help, bundle='pcr查询')

@sv.on_fullmatch('竞技场帮助', only_to_me=False)
async def send_jjchelp(bot, ev):
    await bot.send(ev, f'{sv_help}')

@sv.on_fullmatch('查询群数', only_to_me=False)
async def group_num(bot, ev):
    self_ids = bot._wsr_api_clients.keys()
    for sid in self_ids:
        gl = await bot.get_group_list(self_id=sid)
        msg = f"本Bot目前正在为【{len(gl)}】个群服务"
    await bot.send(ev, f'{msg}')

curpath = dirname(__file__)
config = join(curpath, 'binds.json')
root = {
    'arena_bind' : {}
}

cache = {}
client = None
client_1cx = None
client_2cx = None
client_3cx = None
client_4cx = None
lck = Lock()

if exists(config):
    with open(config) as fp:
        root = load(fp)

binds = root['arena_bind']

captcha_lck = Lock()

with open(join(curpath, 'account.json')) as fp:
    pinfo = load(fp)

if exists(join(curpath, '1cx_tw.sonet.princessconnect.v2.playerprefs.xml')):
    acinfo_1cx = decryptxml(join(curpath, '1cx_tw.sonet.princessconnect.v2.playerprefs.xml'))
    client_1cx = pcrclient(acinfo_1cx['UDID'], acinfo_1cx['SHORT_UDID'], acinfo_1cx['VIEWER_ID'], acinfo_1cx['TW_SERVER_ID'], pinfo['proxy'])
if exists(join(curpath, '2cx_tw.sonet.princessconnect.v2.playerprefs.xml')):
    acinfo_2cx = decryptxml(join(curpath, '2cx_tw.sonet.princessconnect.v2.playerprefs.xml'))
    client_2cx = pcrclient(acinfo_2cx['UDID'], acinfo_2cx['SHORT_UDID'], acinfo_2cx['VIEWER_ID'], acinfo_2cx['TW_SERVER_ID'], pinfo['proxy'])
if exists(join(curpath, '3cx_tw.sonet.princessconnect.v2.playerprefs.xml')):
    acinfo_3cx = decryptxml(join(curpath, '3cx_tw.sonet.princessconnect.v2.playerprefs.xml'))
    client_3cx = pcrclient(acinfo_3cx['UDID'], acinfo_3cx['SHORT_UDID'], acinfo_3cx['VIEWER_ID'], acinfo_3cx['TW_SERVER_ID'], pinfo['proxy'])
if exists(join(curpath, '4cx_tw.sonet.princessconnect.v2.playerprefs.xml')):
    acinfo_4cx = decryptxml(join(curpath, '4cx_tw.sonet.princessconnect.v2.playerprefs.xml'))
    client_4cx = pcrclient(acinfo_4cx['UDID'], acinfo_4cx['SHORT_UDID'], acinfo_4cx['VIEWER_ID'], acinfo_4cx['TW_SERVER_ID'], pinfo['proxy'])

qlck = Lock()

async def query(cx:str, id: str):
    if cx == '1': client = client_1cx
    elif cx == '2': client = client_2cx
    elif cx == '3': client = client_3cx
    else: client = client_4cx
    if client == None:
        return 'lack shareprefs'
    async with qlck:
        while client.shouldLogin:
            await client.login()
        res = (await client.callapi('/profile/get_profile', {
                'target_viewer_id': int(id)
            }))
        return res

def save_binds():
    with open(config, 'w') as fp:
        dump(root, fp, indent=4)

@sv.on_fullmatch('查询竞技场订阅数', only_to_me=False)
async def pcrjjc_number(bot, ev):
    global binds, lck

    async with lck:
        await bot.send(ev, f'当前竞技场已订阅的账号数量为【{len(binds)}】个')

@sv.on_fullmatch('清空竞技场订阅', only_to_me=False)
async def pcrjjc_del(bot, ev):
    global binds, lck

    async with lck:
        if not priv.check_priv(ev, priv.SUPERUSER):
            await bot.send(ev, '抱歉，您的权限不足，只有bot主人才能进行该操作！')
            return
        else:
            num = len(binds)
            binds.clear()
            save_binds()
            await bot.send(ev, f'已清空全部【{num}】个已订阅账号！')

@sv.on_rex(r'^竞技场绑定\s*(\d)\s*(\d{9})$') # 支持匹配空格，空格可有可无且长度无限制
async def on_arena_bind(bot, ev):
    global binds, lck

    if ev['match'].group(1) != '1' and ev['match'].group(1) != '2' and \
        ev['match'].group(1) != '3' and ev['match'].group(1) != '4':
        await bot.send(ev, '服务器选择错误！支持的服务器有1/2/3/4')
        return
    async with lck:
        uid = str(ev['user_id'])
        last = binds[uid] if uid in binds else None

        binds[uid] = {
            'cx': ev['match'].group(1),
            'id': ev['match'].group(2),
            'uid': uid,
            'gid': str(ev['group_id']),
            'arena_on': last is None or last['arena_on'],
            'grand_arena_on': last is None or last['grand_arena_on'],
        }
        save_binds()

    await bot.finish(ev, '竞技场绑定成功', at_sender=True)

@sv.on_rex(r'^竞技场查询\s*(\d)?\s*(\d{9})?$')
async def on_query_arena(bot, ev):
    global binds, lck

    robj = ev['match']
    cx = robj.group(1)
    id = robj.group(2)
    cx_name = _get_cx_name(cx)

    async with lck:
        if id == None and cx == None:
            uid = str(ev['user_id'])
            if not uid in binds:
                await bot.finish(ev, '您还未绑定竞技场', at_sender=True)
                return
            else:
                id = binds[uid]['id']
                cx = binds[uid]['cx']
                cx_name = _get_cx_name(cx)
        try:
            res = await query(cx, id)
            
            if res == 'lack shareprefs':
                await bot.finish(ev, f'查询出错，缺少该服的配置文件', at_sender=True)
                return
            last_login_time = int (res['user_info']['last_login_time'])
            last_login_date = time.localtime(last_login_time)
            last_login_str = time.strftime('%Y-%m-%d %H:%M:%S',last_login_date)
            
            await bot.finish(ev, 
f'''区服：{cx_name}
昵称：{res['user_info']["user_name"]}
jjc排名：{res['user_info']["arena_rank"]}
pjjc排名：{res['user_info']["grand_arena_rank"]}
最后登录：{last_login_str}''', at_sender=False)
        except ApiException as e:
            await bot.finish(ev, f'查询出错，{e}', at_sender=True)

@sv.on_rex(r'^详细查询\s*(\d)?\s*(\d{9})?$')
async def on_query_arena_all(bot, ev):
    global binds, lck

    robj = ev['match']
    cx = robj.group(1)
    id = robj.group(2)

    async with lck:
        if id == None and cx == None:
            uid = str(ev['user_id'])
            if not uid in binds:
                await bot.finish(ev, '您还未绑定竞技场', at_sender=True)
                return
            else:
                id = binds[uid]['id']
                cx = binds[uid]['cx']
        try:
            res = await query(cx, id)
            if res == 'lack shareprefs':
                await bot.finish(ev, f'查询出错，缺少该服的配置文件', at_sender=True)
                return
            sv.logger.info('开始生成竞技场查询图片...') # 通过log显示信息
            result_image = await generate_info_pic(res, cx)
            result_image = pic2b64(result_image) # 转base64发送，不用将图片存本地
            result_image = MessageSegment.image(result_image)
            result_support = await generate_support_pic(res)
            result_support = pic2b64(result_support) # 转base64发送，不用将图片存本地
            result_support = MessageSegment.image(result_support)
            sv.logger.info('竞技场查询图片已准备完毕！')
            try:
                await bot.finish(ev, f"\n{str(result_image)}\n{result_support}", at_sender=True)
            except Exception as e:
                sv.logger.info("do nothing")
        except ApiException as e:
            await bot.finish(ev, f'查询出错，{e}', at_sender=True)

@sv.on_rex('(启用|停止)(公主)?竞技场订阅')
async def change_arena_sub(bot, ev):
    global binds, lck

    key = 'arena_on' if ev['match'].group(2) is None else 'grand_arena_on'
    uid = str(ev['user_id'])

    async with lck:
        if not uid in binds:
            await bot.send(ev,'您还未绑定竞技场',at_sender=True)
        else:
            binds[uid][key] = ev['match'].group(1) == '启用'
            save_binds()
            await bot.finish(ev, f'{ev["match"].group(0)}成功', at_sender=True)

# @on_command('/pcrval')
async def validate(session):
    global binds, lck, validate
    if session.ctx['user_id'] == acinfo_1cx['admin'] or session.ctx['user_id'] == acinfo_2cx['admin'] \
        or session.ctx['user_id'] == acinfo_3cx['admin'] or session.ctx['user_id'] == acinfo_4cx['admin']:
        validate = session.ctx['message'].extract_plain_text().strip()[8:]
        captcha_lck.release()

@sv.on_prefix('删除竞技场订阅')
async def delete_arena_sub(bot,ev):
    global binds, lck

    uid = str(ev['user_id'])

    if ev.message[0].type == 'at':
        if not priv.check_priv(ev, priv.SUPERUSER):
            await bot.finish(ev, '删除他人订阅请联系维护', at_sender=True)
            return
        uid = str(ev.message[0].data['qq'])
    elif len(ev.message) == 1 and ev.message[0].type == 'text' and not ev.message[0].data['text']:
        uid = str(ev['user_id'])


    if not uid in binds:
        await bot.finish(ev, '未绑定竞技场', at_sender=True)
        return

    async with lck:
        binds.pop(uid)
        save_binds()

    await bot.finish(ev, '删除竞技场订阅成功', at_sender=True)

@sv.on_fullmatch('竞技场订阅状态')
async def send_arena_sub_status(bot,ev):
    global binds, lck
    uid = str(ev['user_id'])

    
    if not uid in binds:
        await bot.send(ev,'您还未绑定竞技场', at_sender=True)
    else:
        info = binds[uid]
        await bot.finish(ev,
    f'''
    当前竞技场绑定ID：{info['id']}
    竞技场订阅：{'开启' if info['arena_on'] else '关闭'}
    公主竞技场订阅：{'开启' if info['grand_arena_on'] else '关闭'}''',at_sender=True)


@sv.scheduled_job('interval', minutes=3)
async def on_arena_schedule():
    global cache, binds, lck
    bot = get_bot()
    
    bind_cache = {}

    async with lck:
        bind_cache = deepcopy(binds)


    for user in bind_cache:
        info = bind_cache[user]
        try:
            sv.logger.info(f'querying server[ {info["cx"]} ]: {info["id"]} for {info["uid"]}')
            res = await query(info["cx"], info['id'])
            if res == 'lack shareprefs':
                sv.logger.info(f'由于缺少该服配置文件，已停止')
                # 直接返回吧
                return
            res = (res['user_info']['arena_rank'], res['user_info']['grand_arena_rank'])

            if user not in cache:
                cache[user] = res
                continue

            last = cache[user]
            cache[user] = res

            if res[0] > last[0] and info['arena_on']:
                await bot.send_group_msg(
                    group_id = int(info['gid']),
                    message = f'[CQ:at,qq={info["uid"]}]jjc：{last[0]}->{res[0]} ▼{res[0]-last[0]}'
                )

            if res[1] > last[1] and info['grand_arena_on']:
                await bot.send_group_msg(
                    group_id = int(info['gid']),
                    message = f'[CQ:at,qq={info["uid"]}]pjjc：{last[1]}->{res[1]} ▼{res[1]-last[1]}'
                )
        except ApiException as e:
            sv.logger.info(f'对台服{info["cx"]}服的{info["id"]}的检查出错\n{format_exc()}')
            if e.code == 6:

                async with lck:
                    binds.pop(user)
                    save_binds()
                sv.logger.info(f'已经自动删除错误的uid={info["id"]}')
        except:
            sv.logger.info(f'对台服{info["cx"]}服的{info["id"]}的检查出错\n{format_exc()}')

@sv.on_notice('group_decrease.leave')
async def leave_notice(session: NoticeSession):
    global lck, binds
    uid = str(session.ctx['user_id'])
    
    async with lck:
        if uid in binds:
            binds.pop(uid)
            save_binds()