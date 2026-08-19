async function test() {
  try {
    const res = await fetch('http://127.0.0.1:11434/api/pull', {
      method: 'POST',
      body: JSON.stringify({ name: 'qwen2-vl' })
    });
    console.log(res.status);
  } catch (e) {
    console.log(e.message);
  }
}
test();
