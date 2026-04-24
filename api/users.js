export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  if (req.method === "OPTIONS") return res.status(200).end();

  const secret = req.headers["x-secret"];
  if (secret !== "vpn-secret-2024") return res.status(403).json({ error: "Forbidden" });

  try {
    const response = await fetch("http://194.226.169.15:8765/users", {
      headers: { "X-Secret": "vpn-secret-2024" }
    });
    const data = await response.json();
    res.status(200).json(data);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}
