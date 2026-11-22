# tadawul-web — منصة تداول الذكية (ويب حي)

منصة ويب عربية (RTL، داكنة، تعمل على الجوال) فوق محرك `/workspace/tadawul-brain` (94 وكيلاً: 93 يصوّتون + اللجنة).
FastAPI في الخلف + صفحة واحدة (HTML/JS) في الأمام. لا تكتب في ذاكرة الدماغ (تعادل `run.py --no-persist`).

## التشغيل

```bash
cd /workspace/tadawul-web
./start.sh        # يعيد تشغيل التطبيق + النفق ويطبع الرابط العام، ويكتبه في PUBLIC_URL.txt
./stop.sh         # يوقف الكل
cat PUBLIC_URL.txt
tail -f logs/app.log logs/tunnel.log logs/supervisor.log
```

- `supervise-app.sh`: حلقة إعادة تشغيل تلقائي لـ uvicorn على `127.0.0.1:8080` (بايثون من `tadawul-brain/.venv`، أُضيف له fastapi/uvicorn/apscheduler).
- `supervise-tunnel.sh`: حلقة إعادة تشغيل لـ `bin/cloudflared tunnel --protocol http2 --url http://127.0.0.1:8080` (Quick Tunnel مجاني بلا حساب؛ QUIC محجوب في الصندوق لذلك http2).
- لا يوجد systemd في الصندوق؛ إذا أُعيد تشغيل الصندوق شغّل `./start.sh` يدوياً.
- **الرابط مؤقت**: نطاق `*.trycloudflare.com` يتغير عند كل إعادة تشغيل للنفق. للرابط الدائم: نطاق خاص + حساب Cloudflare (Named Tunnel عبر `cloudflared tunnel login/create/route dns`) أو استضافة VPS/Render/Fly.io مع نفس الكود.

## الحماية

- `.env` (صلاحيات 600) يحوي `ACCESS_TOKEN` عشوائياً طويلاً. افتح `https://<host>/?k=TOKEN` مرة: يضبط كوكي HttpOnly/Secure لمدة 60 يوماً ثم يحوّل للرابط بلا المفتاح.
- كل الصفحات و`/api/*` ترجع 401 بلا الكوكي. `/tv/webhook` يتطلب `?k=TOKEN` (TradingView لا يرسل كوكيز/ترويسات). `/healthz` فقط عام.
- `GROKBOT_WEBHOOK_URL` و`GROKBOT_WEBHOOK_AUTH` (اختياري، فارغ افتراضياً) في `.env` فقط ولا يصلان للمتصفح. إن ضُبطا: يظهر خيار «أرسل لتداول في Grok Bot» في الدردشة، وتُرسل ملخصات تنبيهات TradingView.

## ما في المنصة

1. **اختيار أي سهم عالمي/محلي**: بحث Yahoo Finance من الخادم (`/api/search`) — تداول `.SR`، أمريكا، أوروبا، آسيا، دبي `.AE`، قطر `.QA`، الكويت `.KW`، مصر `.CA`، كريبتو وسلع. اكتب 4 أرقام لرمز سعودي مباشرة.
   - **NOT FOUND**: سوق أبوظبي (ADX، `.AD`) غير متاح على Yahoo في هذه الجلسة.
2. **صفحة السهم**: سعر حي (تحديث كل 30 ثانية؛ الشارت اللحظي يتحدث أثناء فتح السوق)، شارت شموع تفاعلي (lightweight-charts v4.2 محلياً في `static/vendor/`) بإطارات 1D/1W/1M/1Y/5Y، وزر «حلّل بـ94 محلل»: حكم اللجنة، الثقة، الدخول/الوقف/الأهداف (مرسومة على الشارت)، توزيع المجموعات، أنماط الشموع النشطة (أسهم على الشارت)، الثور مقابل الدب، كل المحللين مع السبب والمصدر، قائمة NOT FOUND، وقيود البيانات. التحليل مخزن مؤقتاً 15 دقيقة لكل رمز.
   - الرموز غير السعودية: وكلاء تاسي/ساما/ربط الريال/البتروكيماويات/حالة السوق/إعلانات تداول/ملكية الأجانب/التدفقات/التقويم السعودي/القوة النسبية والبيتا (مقابل KSA)/المقارنة والتناوب القطاعي (نظراء سعوديون) ترجع NOT FOUND «غير منطبق» بدل التخمين (`app/engine_bridge.py:SAUDI_ONLY`). أُضيف للمحرك خيار `fetch_stock(..., saudi_sources=None)` (تلقائي حسب `.SR`).
3. **الرئيسية لكل سوق**: «الأسهم المرشحة» = أحكام «شراء» من الماسح الآلي (وإن لم توجد تُعرض أعلى الأسهم ترتيباً مع التصريح بذلك)، «الصفقات الرابحة» الورقية، إعدادات الشموع الرابحة من الاختبار الخلفي (موسومة «اختبار خلفي»)، وتنبيهات TradingView، وشريط أسعار TradingView.
4. **بوت تداول** (زر 💬 في كل صفحة): إجابات عربية حتمية من مخرجات المحرك (التوصية، المستويات، الشموع، المخاطر، الأسباب، الثور/الدب، المجموعات، المصادر، NOT FOUND، السعر).
5. **إخلاء المسؤولية** في تذييل كل صفحة.

## الماسح الآلي (`app/scanner.py`)

يعمل في خيط خلفي داخل التطبيق، سوقاً بعد سوق مع فاصل دقيقة، بعاملين متوازيين، ويحفظ `data/scans/<MARKET>.json`:

| السوق | الكون | التكرار |
|---|---|---|
| SA | قائمة المراقبة (20) + أسهم تاسي سائلة = 38 | كل 3 ساعات |
| US | أكبر 50 سهماً أمريكياً بالقيمة السوقية (قائمة ثابتة) | كل 6 ساعات |
| GULF | دبي 6 + قطر 4 + الكويت 4 = 14 | كل 8 ساعات |
| EU | 25 من قادة Euro Stoxx/FTSE/SMI | كل 8 ساعات |
| ASIA | 21 (اليابان، هونغ كونغ، كوريا، تايوان، الهند، سنغافورة، أستراليا) | كل 8 ساعات |
| EG | 6 من قادة EGX30 | كل 12 ساعة |

الكون في `app/markets.py`. السهم السعودي يستغرق أطول (مصادر تداول الرسمية تُجرَّب ثم تفشل بمهلة).

## الصفقات الورقية (`app/paper.py`, `data/paper.json`)

- كل حكم «شراء» بوقف وأهداف يفتح صفقة ورقية واحدة لكل رمز (إن لم تكن مفتوحة): من الماسح، التحليل اليدوي، تنبيهات TradingView، وصفوف «شراء» المسجلة سابقاً في `tadawul-brain/decisions.md`.
- الدخول = إغلاق شمعة الإشارة. التقييم بشموع Yahoo اليومية **بعد** تاريخ الإشارة فقط. لمس الوقف والهدف في يوم واحد = وقف. فجوة تحت الوقف = خروج بسعر الافتتاح. بعد T1 يُرفع الوقف لسعر الدخول، والإغلاق عند T3 أو التعادل. «رابحة» = بلغت T1 قبل الوقف.
- يُعاد التقييم كل 30 دقيقة. لا تُختلق صفقات ولا أسعار.

## ربط TradingView (وسائل رسمية/عامة فقط)

- ويدجت TradingView الرسمية المجانية (`s3.tradingview.com/external-embedding/embed-widget-*.js`): Advanced Real-Time Chart (زر «شارت TradingView» بجانب «شارت المحللين»)، Technical Analysis، Symbol Profile، وTicker Tape لكل سوق. تحويل الرموز في `app/yahoo.py:tv_symbol` (مثلاً `2222.SR→TADAWUL:2222`، `AAPL→NASDAQ:AAPL`، `EMAAR.AE→DFM:EMAAR`، `QNBK.QA→QSE:QNBK`، `NBK.KW→KSE:NBK`، `COMI.CA→EGX:COMI`، `0700.HK→HKEX:700`، `ASML.AS→EURONEXT:ASML`، `SAP.DE→XETR:SAP`).
  بعض البورصات قد لا تُعرض بياناتها داخل الويدجت (قيود ترخيص لدى TradingView)؛ عندها يبقى زر «افتح في TradingView» وشارت المحللين.
- زر «افتح في TradingView»: `https://www.tradingview.com/chart/?symbol=EXCHANGE:TICKER`.
- مولّد Pine Script v5: `GET /api/pine?symbol=...` (وزر «📜 سكربت Pine») يرسم منطقة الدخول والوقف والأهداف وملصق الحكم، مع `alertcondition` لكسر الوقف/بلوغ T1/دخول المنطقة. الصقه في Pine Editor ← Add to chart.
- مستقبل تنبيهات TradingView: `POST https://<host>/tv/webhook?k=<ACCESS_TOKEN>` (الرابط الكامل في صفحة «ربط TradingView» داخل المنصة). قالب رسالة التنبيه:

```json
{"ticker":"{{ticker}}","exchange":"{{exchange}}","price":{{close}},"message":"تنبيه سعر"}
```

  عند الوصول: يحوَّل الرمز إلى Yahoo (`TADAWUL:2222→2222.SR`)، يشغَّل المحرك في الخلفية، تُحفظ النتيجة في `data/alerts.json` وتظهر في «تنبيهات TradingView» بالرئيسية، وتُفتح صفقة ورقية إن كان الحكم شراء، ويُرسل ملخص لـ Grok Bot فقط إن ضُبط `GROKBOT_WEBHOOK_URL`.
  **تنبيه:** Webhooks في TradingView تتطلب اشتراكاً مدفوعاً، وتعمل على منفذ 443/https فقط، والرابط المؤقت يتغير عند إعادة تشغيل النفق.
- لا كشط لـ TradingView، ولا واجهات خاصة، ولا أتمتة تسجيل دخول.

## واجهات API (كلها خلف المفتاح)

`/api/config`، `/api/search?q=`، `/api/quote?symbol=`، `/api/chart?symbol=&tf=1D|1W|1M|1Y|5Y`، `/api/analyze?symbol=&force=0|1`، `/api/pine?symbol=`، `/api/home?market=SA|US|EU|GULF|ASIA|EG|CRYPTO`، `/api/paper`، `/api/backtest`، `/api/alerts`، `/api/tvhelp`، `POST /api/chat`، `POST /tv/webhook?k=`.

## الملفات

- `app/main.py` المسارات والحماية · `app/engine_bridge.py` ربط المحرك والتخزين المؤقت · `app/markets.py` الأسواق والأكوان · `app/yahoo.py` الأسعار والبحث وتحويل رموز TradingView · `app/scanner.py` الماسح · `app/paper.py` الصفقات الورقية · `app/tv.py` Pine والتنبيهات · `app/chat.py` البوت
- `static/index.html`، `static/app.js`، `static/style.css`، `static/vendor/lightweight-charts.js`
- `data/` (مسوحات، صفقات، تنبيهات)، `logs/`، `bin/cloudflared`

إخلاء مسؤولية: أداة تعليمية آلية، ليست استشارة مالية مرخّصة.
