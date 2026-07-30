import type { Plugin } from "@opencode-ai/plugin";

const ARTICLES_PATTERN = /knowledge\/articles\/.*\.json$/;

const plugin: Plugin = {
  async "tool.execute.after"(input) {
    const tool = input.tool;
    if (tool !== "write" && tool !== "edit") return;

    const filePath: string | undefined =
      input.args?.file_path ?? input.args?.filePath;
    if (!filePath) return;

    if (!ARTICLES_PATTERN.test(filePath)) return;

    try {
      const result = await $`python3 hooks/validate_json.py ${filePath}`.nothrow();

      if (result.exitCode === 0) return;

      return {
        detail: [
          `---`,
          `### validate_json failed (exit ${result.exitCode})`,
          "```",
          result.stderr.toString().trim() || result.stdout.toString().trim(),
          "```",
        ].join("\n"),
      };
    } catch {
      // shell invocation itself failed (e.g. python3 not found) — don't block
    }
  },
};

export default plugin;
