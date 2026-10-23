/**
 * Cloudflare Worker — daily cron trigger for the GitHub Actions update workflow.
 * Backup for GitHub Actions' built-in cron (which can be unreliable on low-activity repos).
 */

export default {
  async scheduled(event, env) {
    const resp = await fetch(
      "https://api.github.com/repos/Epemstein/terry-awards/actions/workflows/update-data.yml/dispatches",
      {
        method: "POST",
        headers: {
          Authorization: `token ${env.GITHUB_TOKEN}`,
          "User-Agent": "terry-awards-worker",
          Accept: "application/vnd.github.v3+json",
        },
        body: JSON.stringify({ ref: "main" }),
      }
    );
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`GitHub dispatch failed (${resp.status}): ${text}`);
    }
  },

  async fetch(request) {
    return new Response("Terry Awards cron trigger");
  },
};
