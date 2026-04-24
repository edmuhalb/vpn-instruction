export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, DELETE, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Secret");
  if (req.method === "OPTIONS") return res.status(200).end();

  const secret = req.headers["x-secret"];
  if (secret !== "11111111") return res.status(403).json({ error: "Forbidden" });

  try {
    const opts = {
      method: req.method,
      headers: { "Content-Type": "application/json", "X-Secret": "11111111" }
    };
    if (req.method === "DELETE") opts.body = JSON.stringify(req.body);

    const response = await fetch("http://194.226.169.15:8765/users", opts);
    const data = await response.json();
    res.status(200).json(data);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}
