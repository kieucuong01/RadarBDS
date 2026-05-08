import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto('https://guland.vn/post/1-lo-mat-tien-gia-re-duy-nhat-tai-phuong-tan-an-thu-dau-mot-1059738', timeout=60000)
        await page.wait_for_timeout(2000)
        
        imgs = await page.evaluate('''() => {
            return [...document.querySelectorAll('a[href*=".webp"], a[href*=".jpg"]')].map(a => a.href).filter(s => s.includes('cdn.guland.vn'));
        }''')
        print('LINKS:', imgs)
        
        thumbs = await page.evaluate('''() => {
            return [...document.querySelectorAll('img')].map(img => img.src).filter(s => s.includes('cdn.guland.vn'));
        }''')
        print('THUMBS:', thumbs)
        await browser.close()

asyncio.run(main())
