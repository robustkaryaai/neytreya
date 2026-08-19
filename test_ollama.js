const { spawn } = require('child_process');
const ollama = spawn('ollama', ['pull', 'qwen2-vl'], { stdio: ['ignore', 'pipe', 'pipe'] });
ollama.stderr.on('data', d => console.log('stderr:', d.toString()));
ollama.stdout.on('data', d => console.log('stdout:', d.toString()));
ollama.on('close', code => console.log('close:', code));
ollama.on('error', err => console.log('error:', err));
