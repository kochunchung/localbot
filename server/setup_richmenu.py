"""
建立示範用的 Rich Menu（圖文選單），使用 line-bot-sdk v3 寫法。

會建立兩個選單並互相切換：
  主選單：[說哈囉] [開啟網站] [下一頁 ▶]
  第二頁：[◀ 上一頁] [快速回覆範例] [Flex 範例]
並把主選單設為所有使用者的預設選單。

使用方式（先啟動 app.py）：
  python setup_richmenu.py                      # 使用內建的色塊示範圖
  python setup_richmenu.py --image main.png --image2 page2.png   # 使用自己的圖片（2500x843，PNG/JPEG，1 MB 內）
  python setup_richmenu.py --clear              # 刪除所有選單與別名

選單圖片需由你自行設計（不要使用 LINE 的圖示或配色）。
"""
import argparse
import os
import struct
import zlib

from localbot.v3.messaging import (
    ApiClient,
    Configuration,
    CreateRichMenuAliasRequest,
    MessageAction,
    MessagingApi,
    MessagingApiBlob,
    RichMenuArea,
    RichMenuBounds,
    RichMenuRequest,
    RichMenuSize,
    RichMenuSwitchAction,
    URIAction,
)
from localconfig import CHANNEL_ACCESS_TOKEN

PLATFORM_URL = os.environ.get("LOCALBOT_SERVER_URL", "http://localhost:5003")
WIDTH, HEIGHT = 2500, 843


def columns_png(colors, width=WIDTH, height=HEIGHT, gap=8) -> bytes:
    """產生 N 欄色塊的 PNG（只用標準函式庫）。"""
    col_w = width // len(colors)
    row = bytearray(b"\x00")
    for x in range(width):
        idx = min(x // col_w, len(colors) - 1)
        in_gap = x % col_w < gap // 2 or x % col_w >= col_w - gap // 2
        row += bytes((255, 255, 255)) if in_gap else bytes(colors[idx])
    raw = bytes(row) * height

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def labeled_png(colors, labels) -> bytes:
    """有安裝 Pillow 時在色塊上加英文標籤；沒有就用純色塊。"""
    try:
        import io
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return columns_png(colors)
    img = Image.open(io.BytesIO(columns_png(colors))).convert("RGB")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=120)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    col_w = WIDTH // len(labels)
    for i, label in enumerate(labels):
        box = draw.textbbox((0, 0), label, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        draw.text((i * col_w + (col_w - tw) / 2, (HEIGHT - th) / 2 - box[1]), label, fill="white", font=font)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def three_areas(actions):
    w = WIDTH // 3
    return [
        RichMenuArea(bounds=RichMenuBounds(x=i * w, y=0, width=w if i < 2 else WIDTH - 2 * w, height=HEIGHT),
                     action=action)
        for i, action in enumerate(actions)
    ]


def read_image(path, fallback_colors, labels):
    if path:
        with open(path, "rb") as f:
            return f.read()
    return labeled_png(fallback_colors, labels)


def clear(api):
    for alias in api.get_rich_menu_alias_list().aliases:
        api.delete_rich_menu_alias(alias.rich_menu_alias_id)
    for menu in api.get_rich_menu_list().richmenus:
        api.delete_rich_menu(menu.rich_menu_id)
    print("已刪除所有 Rich Menu 與別名")


def main():
    parser = argparse.ArgumentParser(description="建立 LocalBot 示範 Rich Menu")
    parser.add_argument("--image", help="主選單圖片（2500x843）")
    parser.add_argument("--image2", help="第二頁圖片（2500x843）")
    parser.add_argument("--clear", action="store_true", help="刪除所有選單後結束")
    args = parser.parse_args()

    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN, host=PLATFORM_URL)
    with ApiClient(configuration) as client:
        api, blob = MessagingApi(client), MessagingApiBlob(client)
        clear(api)
        if args.clear:
            return

        main_menu = api.create_rich_menu(RichMenuRequest(
            size=RichMenuSize(width=WIDTH, height=HEIGHT),
            selected=True,
            name="main",
            chat_bar_text="選單",
            areas=three_areas([
                MessageAction(label="說哈囉", text="哈囉"),
                URIAction(label="開啟網站", uri="https://github.com/kochunchung/localbot"),
                RichMenuSwitchAction(label="下一頁", rich_menu_alias_id="page-2", data="richmenu=page-2"),
            ]),
        )).rich_menu_id

        page2 = api.create_rich_menu(RichMenuRequest(
            size=RichMenuSize(width=WIDTH, height=HEIGHT),
            selected=True,
            name="page-2",
            chat_bar_text="更多",
            areas=three_areas([
                RichMenuSwitchAction(label="上一頁", rich_menu_alias_id="page-1", data="richmenu=page-1"),
                MessageAction(label="快速回覆", text="quick"),
                MessageAction(label="Flex", text="flex"),
            ]),
        )).rich_menu_id

        blob.set_rich_menu_image(main_menu, body=read_image(args.image, [(79, 70, 229), (14, 165, 142), (99, 102, 241)],
                                                             ["Hello", "Website", "Next >"]))
        blob.set_rich_menu_image(page2, body=read_image(args.image2, [(99, 102, 241), (217, 119, 6), (219, 39, 119)],
                                                         ["< Back", "Quick Reply", "Flex"]))

        api.create_rich_menu_alias(CreateRichMenuAliasRequest(rich_menu_alias_id="page-1", rich_menu_id=main_menu))
        api.create_rich_menu_alias(CreateRichMenuAliasRequest(rich_menu_alias_id="page-2", rich_menu_id=page2))
        api.set_default_rich_menu(main_menu)

        print(f"主選單：{main_menu}（已設為預設）")
        print(f"第二頁：{page2}")
        print("打開 App 就會在輸入列下方看到選單。")


if __name__ == "__main__":
    main()
