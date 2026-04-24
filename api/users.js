export const config = { api: { bodyParser: true } };

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Secret");
  if (req.method === "OPTIONS") return res.status(200).end();

  const secret = req.headers["x-secret"];
  if (secret !== "11111111") return res.status(403).json({ error: "Forbidden" });

  try {
    let bodyStr;
    if (req.method === "DELETE") {
      bodyStr = typeof req.body === "string"
        ? req.body
        : JSON.stringify(req.body || {});
    }

    const response = await fetch("http://194.226.169.15:8765/users", {
      method: req.method,
      headers: {
        "Content-Type": "application/json",
        "X-Secret": "11111111",
        ...(bodyStr ? { "Content-Length": Buffer.byteLength(bodyStr).toString() } : {})
      },
      ...(bodyStr ? { body: bodyStr } : {})
    });

    const text = await response.text();
    try {
      res.status(response.status).json(JSON.parse(text));
    } catch {
      res.status(response.status || 500).json({ error: "Bad response: " + text.slice(0, 300) });
    }
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}
