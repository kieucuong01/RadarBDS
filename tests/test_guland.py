import asyncio
import re
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        page = await b.new_page()
        await page.goto('https://guland.vn/post/1-lo-mat-tien-gia-re-duy-nhat-tai-phuong-tan-an-thu-dau-mot-1059738', timeout=60000)
        await page.wait_for_timeout(2000)
        html = await page.content()
        imgs = re.findall(r'https://cdn\.guland\.vn/[^"\'\s<>]+', html)
        print('FOUND IMAGES:')
        for img in sorted(list(set(imgs))):
            print(img)
        await b.close()

if __name__ == '__main__':
    asyncio.run(main())
