import mod from "@opentui/solid/jsx-runtime";

const EXPECTED = ["jsx","jsxs","jsxDEV","Fragment","jsxTemplate","jsxAttr","jsxEscape"];
const keys = Object.keys(mod);
console.log("Exports:", keys.join(", "));

let ok = true;
for (const e of EXPECTED) {
  const has = keys.includes(e);
  console.log(`  ${has ? "✓" : "✗"} ${e}`);
  if (!has) ok = false;
}

// Functional tests
if (mod.jsxDEV) {
  const r = mod.jsxDEV("div", {class:"t"}, null, false, null, null);
  console.log("  jsxDEV() returns:", JSON.stringify(r));
}
if (mod.jsxs) {
  const r = mod.jsxs("div", {children:["a"]}, null);
  console.log("  jsxs() returns:", JSON.stringify(r));
}
if (mod.Fragment) {
  console.log("  Fragment:", typeof mod.Fragment);
}

process.exit(ok ? 0 : 1);
