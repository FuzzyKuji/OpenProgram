// Loaded into the Playwright MCP process that drives the user's own Chrome or
// Edge. Playwright brings a tab to the front whenever the Agent switches to
// it, and opens new tabs in front; neither has an option, and both pull the
// page away from a person who is using the browser. Once connected with a
// token, the extension also focuses the browser's window; its own
// background option turns that off. The browser coming in front of the other
// applications when the connect page opens is Chrome's doing and is undone
// by computer_use_agent/desktop/front.py.
"use strict";

const Module = require("module");
const EDITS = [
  ['url3.searchParams.set("token", token);',
    '{ url3.searchParams.set("token", token); url3.searchParams.set("background", "true"); }'],
  ['"chrome.tabs.create", [{ url: url3 }]', '"chrome.tabs.create", [{ url: url3, active: false }]'],
  ['throw new Error(`Tab ${index} not found`);\n        await tab2.page.bringToFront();',
    "throw new Error(`Tab ${index} not found`);"],
];

const compile = Module.prototype._compile;
Module.prototype._compile = function (content, filename) {
  if (/playwright-core[\\/]lib[\\/]coreBundle\.js$/.test(filename)) {
    for (const [from, to] of EDITS) {
      if (content.includes(from)) content = content.replace(from, to);
      else process.stderr.write(`playwright_background_tabs: not found in this Playwright: ${from}\n`);
    }
  }
  return compile.call(this, content, filename);
};
