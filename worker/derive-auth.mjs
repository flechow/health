// Liczy REFRESH_AUTH_HASH z Twojego DATA_PASSPHRASE — dokładnie tak samo jak przeglądarka
// (funkcja deriveAuth w index.html): PBKDF2-SHA256, salt "protokol-refresh-auth-v1", 100000 iteracji, 32 bajty, hex.
//
// Użycie (bez podawania hasła w argumentach, żeby nie trafiło do historii powłoki):
//   node derive-auth.mjs
//   (skrypt zapyta o hasło)
// albo:  echo -n "moje-haslo" | node derive-auth.mjs -
//
// Wynik wklej do sekretu Workera:  wrangler secret put REFRESH_AUTH_HASH

import { pbkdf2Sync } from "node:crypto";
import { createInterface } from "node:readline";

const SALT = "protokol-refresh-auth-v1";
const ITER = 100000;

function hashOf(pass) {
  return pbkdf2Sync(Buffer.from(pass, "utf8"), Buffer.from(SALT, "utf8"), ITER, 32, "sha256").toString("hex");
}

async function readPass() {
  // "-" => czytaj z stdin (np. z echo -n ... | node ...)
  if (process.argv[2] === "-") {
    const chunks = [];
    for await (const c of process.stdin) chunks.push(c);
    return Buffer.concat(chunks).toString("utf8").replace(/\r?\n$/, "");
  }
  if (process.argv[2]) return process.argv[2];        // node derive-auth.mjs "haslo"
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((res) => rl.question("DATA_PASSPHRASE: ", (a) => { rl.close(); res(a); }));
}

const pass = await readPass();
if (!pass) { console.error("Puste hasło."); process.exit(1); }
console.log(hashOf(pass));
