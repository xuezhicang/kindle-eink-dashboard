/**
 * Welcome to Cloudflare Workers! This is your first worker.
 *
 * - Run "npm run dev" in your terminal to start a development server
 * - Open a browser tab at http://localhost:8787/ to see your worker in action
 * - Run "npm run deploy" to publish your worker
 *
 * Learn more at https://developers.cloudflare.com/workers/
 */


const IMAGE_KEY = "dashboard.png";
const MAX_IMAGE_SIZE = 2 * 1024 * 1024; // 2 MB

function authorized(request, token) {
  if (!token) return false;

  return request.headers.get("Authorization") ===
    `Bearer ${token}`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // Health check: no private data
    if (path === "/health" && request.method === "GET") {
      return new Response("OK");
    }

    // Upload image from GitHub Actions
    if (path === "/image.png" && request.method === "PUT") {
      if (!authorized(request, env.UPLOAD_TOKEN)) {
        return new Response("Unauthorized", { status: 401 });
      }

      if (request.headers.get("Content-Type") !== "image/png") {
        return new Response("PNG required", { status: 415 });
      }

      const body = await request.arrayBuffer();

      if (body.byteLength === 0 || body.byteLength > MAX_IMAGE_SIZE) {
        return new Response("Invalid image size", { status: 413 });
      }

      // Verify PNG signature
      const header = new Uint8Array(body.slice(0, 8));
      const signature = [137, 80, 78, 71, 13, 10, 26, 10];

      if (!signature.every((byte, i) => header[i] === byte)) {
        return new Response("Invalid PNG", { status: 400 });
      }

      await env.IMAGES.put(IMAGE_KEY, body);

      return new Response("Uploaded", { status: 200 });
    }

    // Download image to Kindle
    if (path === "/image.png" && request.method === "GET") {
      if (!authorized(request, env.READ_TOKEN)) {
        return new Response("Unauthorized", { status: 401 });
      }

      const image = await env.IMAGES.get(IMAGE_KEY, "arrayBuffer");

      if (!image) {
        return new Response("No image uploaded yet", { status: 404 });
      }

      return new Response(image, {
        status: 200,
        headers: {
          "Content-Type": "image/png",
          "Cache-Control": "private, no-store",
          "X-Content-Type-Options": "nosniff"
        }
      });
    }

    return new Response("Not Found", { status: 404 });
  }
};
