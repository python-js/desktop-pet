const task = await taskSpace("desktop-pet-pixel-toggle");
const page = task.page("p1");
await page.goto("https://leibox.pantoria.cn/docs/animations/pixel-toggle");
console.log(await page.title());
console.log((await page.snapshot()).slice(0, 18000));
await task.finish({ keep: [] });
