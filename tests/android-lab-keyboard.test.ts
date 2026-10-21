import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { expect, it } from "vitest";

// Evaluate only the owned AVD setup's keyboard policy expression. Never run
// prepare(), touch an SDK/AVD, or invoke ADB from this regression.
const values = JSON.parse(execFileSync("python3", ["-B", "-c", `
import ast, json, pathlib, sys
module = ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
policies = [value for node in ast.walk(module) if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and key.value == "hw.keyboard"]
assert len(policies) == 1, "Expected one owned AVD keyboard policy"
expression = compile(ast.Expression(policies[0]), "<keyboard-policy>", "eval")
print(json.dumps({profile: eval(expression, {"__builtins__": {}}, {"profile": profile})
                  for profile in ("phone", "fold")}))
`, resolve("scripts/android-lab.py")], { encoding: "utf8" })) as Record<string, string>;

it("uses an on-screen keyboard for the isolated phone emulator", () => {
  expect(values.phone).toBe("no");
});

it("preserves the existing fold emulator keyboard policy", () => {
  expect(values.fold).toBe("yes");
});
