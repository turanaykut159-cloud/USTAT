/**
 * PNG ikon oluşturucu.
 *
 * Kullanım: node assets/generate-icon.js
 *
 * Bu script Canvas API kullanarak 256x256 PNG ikon oluşturur.
 * Electron hem PNG hem ICO destekler; Windows için ICO
 * electron-builder tarafından PNG'den otomatik oluşturulur.
 */

const { createCanvas } = require('canvas');
const fs = require('fs');
const path = require('path');

const SIZE = 256;
const canvas = createCanvas(SIZE, SIZE);
const ctx = canvas.getContext('2d');

// ── Arka plan ─────────────────────────────────────────────────────
const bgGrad = ctx.createLinearGradient(0, 0, SIZE, SIZE);
bgGrad.addColorStop(0, '#0d1117');
bgGrad.addColorStop(1, '#161b22');

// Yuvarlak köşeli kare
const r = 40;
ctx.beginPath();
ctx.moveTo(r, 0);
ctx.lineTo(SIZE - r, 0);
ctx.quadraticCurveTo(SIZE, 0, SIZE, r);
ctx.lineTo(SIZE, SIZE - r);
ctx.quadraticCurveTo(SIZE, SIZE, SIZE - r, SIZE);
ctx.lineTo(r, SIZE);
ctx.quadraticCurveTo(0, SIZE, 0, SIZE - r);
ctx.lineTo(0, r);
ctx.quadraticCurveTo(0, 0, r, 0);
ctx.closePath();
ctx.fillStyle = bgGrad;
ctx.fill();

// Border
ctx.strokeStyle = '#30363d';
ctx.lineWidth = 2;
ctx.stroke();

// ── Chart çizgisi ─────────────────────────────────────────────────
const points = [
  [40, 180], [70, 165], [95, 170], [120, 140],
  [145, 150], [170, 110], [195, 95], [220, 70],
];

ctx.beginPath();
ctx.moveTo(points[0][0], points[0][1]);
for (let i = 1; i < points.length; i++) {
  ctx.lineTo(points[i][0], points[i][1]);
}
const lineGrad = ctx.createLinearGradient(40, 180, 220, 70);
lineGrad.addColorStop(0, '#238636');
lineGrad.addColorStop(1, '#3fb950');
ctx.strokeStyle = lineGrad;
ctx.lineWidth = 4;
ctx.lineCap = 'round';
ctx.lineJoin = 'round';
ctx.stroke();

// Noktalar
[[120, 140], [170, 110], [220, 70]].forEach(([x, y]) => {
  ctx.beginPath();
  ctx.arc(x, y, 4, 0, Math.PI * 2);
  ctx.fillStyle = '#3fb950';
  ctx.fill();
});

// ── "U" harfi ─────────────────────────────────────────────────────
ctx.font = 'bold 120px "Segoe UI", Arial, sans-serif';
ctx.textAlign = 'center';
ctx.textBaseline = 'middle';
ctx.fillStyle = '#58a6ff';
ctx.globalAlpha = 0.9;
ctx.fillText('U', SIZE / 2, SIZE / 2 + 10);
ctx.globalAlpha = 1.0;

// ── Kaydet ────────────────────────────────────────────────────────
const buffer = canvas.toBuffer('image/png');
const outPath = path.join(__dirname, 'icon.png');
fs.writeFileSync(outPath, buffer);
console.log(`Icon oluşturuldu: ${outPath} (${buffer.length} bytes)`);
