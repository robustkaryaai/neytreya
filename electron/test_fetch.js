async function test() {
  try {
    const res = await fetch('http://127.0.0.1:11434/');
    console.log(await res.text());
  } catch (e) {
    console.log(e.message);
  }
}
test();
