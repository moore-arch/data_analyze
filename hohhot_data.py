import os.path
import re

import aiohttp
import asyncio
from bs4 import BeautifulSoup
import matplotlib.pyplot as plt


def get_sign_value(match: re.Match, name: str):
    if any(char in set('下降低负') for char in match.group(f'{name}_trend')):
        return -float(match.group(name))
    return float(match.group(name))


class BaseInfo:
    """数值，同比，环比"""
    def __init__(self, *args):
        if len(args) == 2 and isinstance(args[0], re.Match) and isinstance(args[1], str):
            match_result, name = args
            self.value = float(match_result.group(name))
            self.yoy = get_sign_value(match_result, f'{name}_yoy')
            self.mom = get_sign_value(match_result, f'{name}_mom')
        elif len(args) == 3 and all(isinstance(arg, (int, float)) for arg in args):
            self.value, self.yoy, self.mom = args
        else:
            print(f'args={args}')
            raise ValueError("Invalid arguments. Expected one match object or three numeric values.")


class HouseInfo:

    def __init__(self, commercial_match=None, residential_match=None):
        if commercial_match is None or residential_match is None:
            pass
        # 商品房销售
        self.commercial_area = BaseInfo(commercial_match, 'area')
        self.commercial_unit = BaseInfo(commercial_match, 'unit')

        # 商品住宅销售
        self.residential_area = BaseInfo(residential_match, 'area')
        self.residential_unit = BaseInfo(residential_match, 'unit')


class TradeInfo:
    def __init__(self, year: int, month: int, href: str):
        self.year = year
        self.month = month
        self.href = href.strip().removeprefix('./')

        # 新建商品房上市数据
        self.commercial_list_info = None
        self.residential_list_info = None

        """新房、旧房交易数据"""
        self.new_house = None
        self.old_house = None

    def __str__(self):
        return f"{self.year}-{self.month}: {self.href}"

    def __repr__(self):
        return self.__str__()


month_info_list = []

num = r'\d+\.\d+|\d+'
trend = r'[增下上][长降涨]'
# 匹配新建商品房上市面积信息
commercial_list_pattern = re.compile(rf'\d+月，我市商品房上市面积(?P<area>{num})万平方米，'
                                     rf'同比(?P<area_mom_trend>{trend})(?P<area_mom>{num})%，'
                                     rf'环比(?P<area_yoy_trend>{trend})(?P<area_yoy>{num})%')

# 匹配新建商品住房面积信息
residential_list_pattern = re.compile(rf'商品住房上市面积(?P<area>{num})万平方米，'
                                      rf'同比(?P<area_mom_trend>{trend})(?P<area_mom>{num})%?，'
                                      rf'环比(?P<area_yoy_trend>{trend})(?P<area_yoy>{num})%')


def build_deal_pattern(prefix: str):
    return re.compile(rf'{prefix}(?P<area>{num})万平方米，'
                      rf'同比(?P<area_yoy_trend>{trend})(?P<area_yoy>{num})%，'
                      rf'环比(?P<area_mom_trend>{trend})(?P<area_mom>{num})%[；|。]'
                      rf'成交套数(?P<unit>\d+)套，'
                      rf'同比(?P<unit_yoy_trend>{trend})(?P<unit_mom>{num})%，'
                      rf'环比(?P<unit_mom_trend>{trend})(?P<unit_yoy>{num})%。')


# 新建商品房销售情况
new_commercial_deal_pattern = build_deal_pattern(r'我市新建商品房成交面积')

# 新建商品住宅销售数据
new_residential_deal_pattern = build_deal_pattern(r'其中：新建商品住宅成交面积')

old_commercial_deal_pattern = build_deal_pattern(r'我市二手房成交面积')
old_residential_deal_pattern = build_deal_pattern(r'其中：二手住宅成交面积')


async def fetch_content(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text()
            return html


async def fetch_html_content(dump_file: str, suffix: str):
    if os.path.exists(dump_file) and os.path.getsize(dump_file) > 0:
        print(f'read html from file: {dump_file}')
        with open(dump_file, 'rb') as fin:
            html_content = fin.read()
    else:
        url = f'http://zfcxjsj.huhhot.gov.cn/tjsj/{suffix}'
        print(f'fetch html from url: {url}')
        html_content = await fetch_content(url)
        with open(dump_file, 'wb') as f:
            f.write(html_content.encode('utf-8'))
    return html_content


async def fill_month_trade_info(trade_info: TradeInfo, dump_file=None):
    if dump_file is None:
        dump_file = os.path.join(os.path.dirname(__file__), f'{trade_info.year}-{trade_info.month}-trade-info.html')
    html_content = await fetch_html_content(dump_file, trade_info.href)

    soup = BeautifulSoup(html_content, 'lxml')
    para = soup.find(name='div', id='para')
    content = para.get_text(strip=True)
    print(f'content = {content}')

    trade_info.commercial_list_info = BaseInfo(commercial_list_pattern.search(content), 'area')
    trade_info.residential_list_info = BaseInfo(residential_list_pattern.search(content), 'area')

    new_commercial_deal_info = new_commercial_deal_pattern.search(content)
    new_residential_deal_info = new_commercial_deal_pattern.search(content)

    old_commercial_deal_info = old_commercial_deal_pattern.search(content)
    old_residential_deal_info = old_commercial_deal_pattern.search(content)

    trade_info.new_house = HouseInfo(new_commercial_deal_info, new_residential_deal_info)
    trade_info.old_house = HouseInfo(old_commercial_deal_info, old_residential_deal_info)

    return trade_info


async def process_index_page(page_id: str):
    print(f'begin process {page_id}')
    title_pattern = re.compile(r'(\d{4})年(\d{1,2})月[我|市]*房地产[市|场]*[运行]*情况')
    html_content = await fetch_html_content(page_id, page_id)
    soup = BeautifulSoup(html_content, 'html.parser')
    month_tags = soup.find_all('a', target='_blank', title=title_pattern)
    print(f'month_tags={month_tags}')
    for month_tag in month_tags:
        href = month_tag.get('href')
        title = month_tag.get('title')
        match_res = re.match(title_pattern, title)
        year, month = match_res.group(1), match_res.group(2)
        print(f'href={href}, title={title}, year={year},m={month}')
        month_trade_info = TradeInfo(year, month, href)
        try:
            await fill_month_trade_info(month_trade_info, f'{title}.html')
            month_info_list.append(month_trade_info)
        except:
            print(f'drop: {year}-{month}')


async def fetch_business_data():
    page_ids = ['index.html']
    page_ids += [f'index_{idx}.html' for idx in range(1, 8)]
    print(page_ids)
    for page_id in page_ids:
        await process_index_page(page_id)


if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    # loop.run_until_complete(process_index_page('index.html'))
    loop.run_until_complete(fetch_business_data())
    month_info_list.sort(key=lambda obj: (obj.year, obj.month), reverse=False)


    x = [f'{obj.year}{obj.month}' for obj in month_info_list]

    plt.figure()
    plt.plot(x, [obj.commercial_list_info.value for obj in month_info_list]) # 新建商品房面积
    plt.title('commercial_list_info')
    plt.legend()

    plt.figure()
    plt.plot(x, [obj.residential_list_info.value for obj in month_info_list]) # 新建住宅面积
    plt.title('residential_list_info')
    plt.legend()

    plt.figure()
    plt.plot(x, [obj.new_house.commercial_area.value for obj in month_info_list]) # 新建商品房成交面积
    plt.title('new_house.commercial_area')
    plt.legend()

    plt.figure()
    plt.plot(x, [obj.new_house.commercial_unit.value for obj in month_info_list])  # 新建商品房成交套数
    plt.title('new_house.commercial_unit')
    plt.legend()

    plt.figure()
    plt.plot(x, [obj.new_house.residential_area.value for obj in month_info_list])  # 新建商品房成交面积
    plt.title('new_house.residential_area')
    plt.legend()

    plt.figure()
    plt.plot(x, [obj.new_house.residential_unit.value for obj in month_info_list])  # 新建商品房成交套数
    plt.title('new_house.residential_unit')
    plt.legend()

    plt.figure()
    plt.plot(x, [obj.old_house.residential_unit.value for obj in month_info_list])  # 二手住宅成交套数
    plt.title('old_house.residential_unit')
    plt.legend()

    plt.figure()
    plt.plot(x, [obj.old_house.residential_area.value for obj in month_info_list])  # 二手建住宅成交面积
    plt.title('old_house.residential_area')
    plt.legend()

    plt.figure()
    plt.plot(x, [obj.new_house.residential_area.value / obj.new_house.residential_unit.value for obj in month_info_list])  # 新建商品房成交套数
    plt.title('new_house.residential_avg_area_per_house')
    plt.legend()

    plt.figure()
    plt.plot(x, [obj.old_house.residential_area.value / obj.old_house.residential_unit.value for obj in month_info_list])  # 新建商品房成交套数
    plt.title('old_house.residential_avg_area_per_house')
    plt.legend()

    plt.xticks(rotation=45)
    plt.show()

