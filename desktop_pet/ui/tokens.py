"""设计 token 唯一来源，对应 UInew/控制台高清分页/design-tokens.css。"""
from dataclasses import dataclass

FONT_UI = 'Microsoft YaHei UI'
FONT_DISPLAY = FONT_UI
FONT_MONO = 'Cascadia Mono'

# 尺寸常量（4px 基网格）
RAIL_W = 232
RAIL_W_COLLAPSED = 68
WINBAR_H = 38
SIDEBAR_PAD = 12
NAV_H = 36
CTL_H = 32
CTL_H_LG = 38
ROW_H = 58
ROW_H_SM = 44
RADIUS_CTL = 10
RADIUS_CARD = 14
RADIUS_PILL = 999


@dataclass(frozen=True)
class Tokens:
    name: str
    bg: str
    surface: str
    surface_2: str
    surface_3: str
    border: str
    border_strong: str
    ink: str
    ink_2: str
    ink_3: str
    ink_4: str
    brand: str
    brand_hover: str
    brand_press: str
    brand_on: str
    brand_wash: str
    brand_line: str
    alert: str
    alert_wash: str
    caution: str
    caution_wash: str
    calm: str
    calm_wash: str
    info: str
    info_wash: str


LIGHT = Tokens(
    name='light',
    bg='#F7F6F4',
    surface='#FFFFFF',
    surface_2='#F1EFEC',
    surface_3='#E9E6E1',
    border='#E3E0DB',
    border_strong='#CFCAC2',
    ink='#1B1A18',
    ink_2='#55524C',
    ink_3='#86827A',
    ink_4='#ADA89F',
    brand='#C24E2E',
    brand_hover='#A94125',
    brand_press='#8E3418',
    brand_on='#FFFFFF',
    brand_wash='#FAEAE3',
    brand_line='#F0CDBF',
    alert='#A02419',
    alert_wash='#FBEBE8',
    caution='#8A5A00',
    caution_wash='#FBF1DC',
    calm='#4F6B3A',
    calm_wash='#EDF2E7',
    info='#2F5D7C',
    info_wash='#E8F0F5',
)

DARK = Tokens(
    name='dark',
    bg='#17181A',
    surface='#1F2124',
    surface_2='#26282C',
    surface_3='#303338',
    border='#2E3134',
    border_strong='#3E4248',
    ink='#ECEAE6',
    ink_2='#A9A6A0',
    ink_3='#7E7B74',
    ink_4='#5C5A55',
    brand='#E4703F',
    brand_hover='#EE8454',
    brand_press='#C85E31',
    brand_on='#1A0E08',
    brand_wash='#3A2318',
    brand_line='#5C3626',
    alert='#EE6B5E',
    alert_wash='#3B1F1C',
    caution='#E0A94B',
    caution_wash='#362B16',
    calm='#8FB56B',
    calm_wash='#22301B',
    info='#7FB3D2',
    info_wash='#1B2A33',
)


def get(name):
    return DARK if name == 'dark' else LIGHT
