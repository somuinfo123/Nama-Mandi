# Mandi Rates · ಮಂಡಿ ದರ — free price app for farmers

A one-file web app (`index.html`). The farmer:
1. picks a crop (Kannada / English),
2. taps **Find my nearest mandi** (GPS) or picks an APMC from the list,
3. enters a **sowing date** (the days to harvest are pre-filled for each crop and can be changed),

and gets:
- the **predicted rate at harvest** for that mandi, with a likely range, plus the rate 1–2 months later in case they store the crop,
- how accurate the method has been at that mandi (it is tested on that mandi's own past data),
- the actual rate in the same month in past years,
- the latest rate, whether it is high, average or low against the last 12 months, the price history, the best months to sell, and nearby mandis compared.

All prices are free government AGMARKNET data from data.gov.in ("Variety-wise Daily Market Prices", resource `579b464db66ec23bdd000001239054491c3e4ebd4d6e3d0eb373eb06`). The app has no server, database, login or ads.

## Preview it now
Open `index.html#demo` in a browser. It shows a yellow **DEMO** banner and uses made-up sample prices, so you can see how the app works.

## Go live (about 15 minutes, free)
1. **Get an API key.** Sign up at https://data.gov.in, then go to **My Account → Generate API key**.
2. **Put the key in the file.** Open `index.html` and find `CONFIG` near the top of the script. Paste your key into `API_KEY: ""`.
3. **Host the file.** Either of these works:
   - **GitHub Pages:** create a public repo, upload `index.html`, then go to **Settings → Pages → Deploy from branch**. The link will be `https://<you>.github.io/<repo>/`.
   - **Your Farmers Point website:** upload the file as, for example, `farmerspoint.in/rates/`.

   The site must use **https**, or phone GPS won't work.
4. **Test on a phone.** Pick a crop, tap **Find my nearest mandi**, then enter a sowing date.
5. **Share the link** on WhatsApp. Farmers can tap **Add to Home screen** so it opens like an app.

### If prices don't load ("browser blocked the request")
Some data.gov.in endpoints refuse requests made directly from a browser. If yours does, set up this free Cloudflare Worker as a proxy:

```js
// Cloudflare dashboard → Workers → Create → paste → Deploy
export default {
  async fetch(req) {
    const target = new URL(req.url).searchParams.get("url");
    if (!target || !target.startsWith("https://api.data.gov.in/")) return new Response("bad url", { status: 400 });
    const r = await fetch(target, { cf: { cacheTtl: 21600, cacheEverything: true } });
    return new Response(r.body, { status: r.status, headers: {
      "content-type": "application/json", "access-control-allow-origin": "*" } });
  }
};
```
Then set `PROXY: "https://<your-worker>.workers.dev/?url="` in `CONFIG`. The worker also caches results for 6 hours, which makes the app faster for everyone.

## How the harvest-price prediction works
1. Daily modal prices are averaged into monthly prices for the chosen mandi, crop and variety.
2. **Seasonal pattern:** each year's monthly prices are divided by that year's average, then the results are averaged across years. For example, onion usually comes out cheap in Mar–Apr and costly in Sep–Oct.
3. **Trend:** a straight-line trend is fitted on the last 36 months after removing the seasonal effect. The slope is halved to avoid over-reacting and capped at ±2% per month.
4. **Prediction for the harvest month** = the recent level (the last 3 months) × the trend × that month's seasonal factor.
5. **Likely range:** the method is re-run at every past month using only the data available then. It is checked against what actually happened at the same horizon. The range shown covers 8 out of 10 of those past outcomes.

The app needs at least 18 months of data at a mandi to predict. Small mandis with few reports show a message suggesting a bigger nearby mandi. This is a planning guide: it cannot know future rainfall, MSP changes or market shocks, and the app says so on screen.

## Things to adjust
- **Crop list, Kannada names and harvest durations:** see the `CROPS` and `DUR` lists in the script.
- **Another state:** change `STATE` and add that state's towns to `TOWNS`. `TOWNS` holds approximate coordinates, used to find the nearest mandi.
- **Mandi names that aren't recognised:** these fall back to their district's location. Add the name as an alias in `TOWNS`.
- **Speed:** results are cached on the phone for 12 hours (`CACHE_HOURS`).

## Next steps if farmers like it
- Wrap it as an Android app with a free Trusted Web Activity (Bubblewrap) and list it on the Play Store.
- Add a WhatsApp or SMS price alert, for example "Onion at Annigeri crossed ₹2,500".
- Add rainfall and sowing-area data to improve predictions for the crops that need it.
