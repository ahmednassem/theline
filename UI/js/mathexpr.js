// Safe math expression evaluator for plots ("sin(x) * exp(-x/4)").
// Tiny tokenizer + shunting-yard + stack evaluator. No eval(), no Function().
// Supports: + - * / ^, parentheses, unary minus, variable x,
// functions sin cos tan asin acos atan sqrt abs exp log floor ceil,
// constants pi and e.

const FUNCS = {
  sin: Math.sin, cos: Math.cos, tan: Math.tan,
  asin: Math.asin, acos: Math.acos, atan: Math.atan,
  sqrt: Math.sqrt, abs: Math.abs, exp: Math.exp,
  log: Math.log, floor: Math.floor, ceil: Math.ceil,
};
const CONSTS = { pi: Math.PI, e: Math.E };
const OPS = {
  "+": { prec: 1, fn: (a, b) => a + b },
  "-": { prec: 1, fn: (a, b) => a - b },
  "*": { prec: 2, fn: (a, b) => a * b },
  "/": { prec: 2, fn: (a, b) => a / b },
  "^": { prec: 3, right: true, fn: (a, b) => Math.pow(a, b) },
};

function tokenize(src) {
  const tokens = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (c === " " || c === "\t") { i++; continue; }
    if (/[0-9.]/.test(c)) {
      let j = i;
      while (j < src.length && /[0-9.]/.test(src[j])) j++;
      tokens.push({ t: "num", v: parseFloat(src.slice(i, j)) });
      i = j;
    } else if (/[a-zA-Z_]/.test(c)) {
      let j = i;
      while (j < src.length && /[a-zA-Z_]/.test(src[j])) j++;
      tokens.push({ t: "name", v: src.slice(i, j).toLowerCase() });
      i = j;
    } else if (c in OPS || c === "(" || c === ")" || c === ",") {
      tokens.push({ t: c });
      i++;
    } else {
      throw new Error(`bad char in expression: ${c}`);
    }
  }
  return tokens;
}

// Compile to RPN once; evaluate many times.
export function compileExpr(src) {
  const tokens = tokenize(src);
  const out = [];
  const stack = [];
  let prev = null;
  for (const tok of tokens) {
    if (tok.t === "num") out.push(tok);
    else if (tok.t === "name") {
      if (tok.v in FUNCS) stack.push({ t: "fn", v: tok.v });
      else if (tok.v in CONSTS) out.push({ t: "num", v: CONSTS[tok.v] });
      else if (tok.v === "x") out.push({ t: "var" });
      else throw new Error(`unknown name: ${tok.v}`);
    } else if (tok.t === "(") stack.push(tok);
    else if (tok.t === ")") {
      while (stack.length && stack[stack.length - 1].t !== "(") out.push(stack.pop());
      stack.pop();
      if (stack.length && stack[stack.length - 1].t === "fn") out.push(stack.pop());
    } else if (tok.t in OPS) {
      // unary minus -> 0 - v
      const unary = tok.t === "-" && (!prev || prev.t === "(" || prev.t in OPS);
      if (unary) out.push({ t: "num", v: 0 });
      const o = OPS[tok.t];
      while (stack.length) {
        const top = stack[stack.length - 1];
        if (top.t in OPS && (OPS[top.t].prec > o.prec || (OPS[top.t].prec === o.prec && !o.right))) {
          out.push(stack.pop());
        } else break;
      }
      stack.push(tok);
    }
    prev = tok;
  }
  while (stack.length) out.push(stack.pop());

  return function evaluate(x) {
    const st = [];
    for (const tok of out) {
      if (tok.t === "num") st.push(tok.v);
      else if (tok.t === "var") st.push(x);
      else if (tok.t === "fn") st.push(FUNCS[tok.v](st.pop()));
      else if (tok.t in OPS) {
        const b = st.pop(), a = st.pop();
        st.push(OPS[tok.t].fn(a, b));
      }
    }
    return st.pop();
  };
}
