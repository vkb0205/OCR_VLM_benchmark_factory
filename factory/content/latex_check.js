// Read a JSON list of LaTeX strings on stdin; print one error string (or null) per item.
const katex = require(process.argv[2]);
const items = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(items.map(([latex, display]) => {
  try { katex.renderToString(latex, {displayMode: display, throwOnError: true, strict: 'error', output: 'html'}); return null; }
  catch (e) { return String(e.message || e); }
})));
