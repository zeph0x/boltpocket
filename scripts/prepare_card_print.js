#!/usr/bin/env node
/**
 * Prepare card print assets for shopnfc.com variable data printing.
 *
 * Input:  CSV from BoltPocket admin wallet generator
 * Output: Per-card assets + Excel-ready CSV + example layout image
 *
 * Usage:
 *   node scripts/prepare_card_print.js wallets.csv --output-dir card_print/
 *   node scripts/prepare_card_print.js wallets.csv --output-dir card_print/ --template-front front.png --template-back back.png
 *
 * Output structure:
 *   card_print/
 *     print_data.csv          — Excel-ready: card_number, name, qr_file, identicon_file, ln_address
 *     identicons/
 *       card_001_identicon.png
 *       card_002_identicon.png
 *     qrcodes/
 *       card_001_qr.png
 *       card_002_qr.png
 *     examples/
 *       card_001_back.png     — Example composited back
 */

const fs = require('fs');
const path = require('path');
const jdenticon = require('jdenticon');

// Parse args
const args = process.argv.slice(2);
let csvFile = null;
let outputDir = 'card_print';
let templateFront = null;
let templateBack = null;

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--output-dir' && args[i+1]) { outputDir = args[++i]; }
  else if (args[i] === '--template-front' && args[i+1]) { templateFront = args[++i]; }
  else if (args[i] === '--template-back' && args[i+1]) { templateBack = args[++i]; }
  else if (!csvFile) { csvFile = args[i]; }
}

if (!csvFile) {
  console.error('Usage: node prepare_card_print.js <wallets.csv> [--output-dir dir]');
  process.exit(1);
}

// Parse CSV
function parseCSV(text) {
  const lines = text.trim().split('\n');
  const headers = lines[0].split(',');
  return lines.slice(1).map(line => {
    const values = line.split(',');
    const row = {};
    headers.forEach((h, i) => row[h.trim()] = (values[i] || '').trim());
    return row;
  });
}

const csvText = fs.readFileSync(csvFile, 'utf-8');
const wallets = parseCSV(csvText);

console.log(`Loaded ${wallets.length} wallets from ${csvFile}`);

// Create output dirs
const identiconDir = path.join(outputDir, 'identicons');
const qrcodeDir = path.join(outputDir, 'qrcodes');
const examplesDir = path.join(outputDir, 'examples');
fs.mkdirSync(identiconDir, { recursive: true });
fs.mkdirSync(qrcodeDir, { recursive: true });
fs.mkdirSync(examplesDir, { recursive: true });

// Generate assets
const printRows = [];

wallets.forEach((w, i) => {
  const num = String(i + 1).padStart(3, '0');
  const name = w.name || `Card ${i + 1}`;
  const lnAddress = w.ln_address || '';
  const walletUrl = w.wallet_url || '';

  // Identicon SVG + PNG (300 DPI at 20mm ≈ 236px, use 400px for safety)
  const identiconSvg = jdenticon.toSvg(lnAddress, 400);
  const identiconPng = jdenticon.toPng(lnAddress, 400);
  const identiconSvgFile = `card_${num}_identicon.svg`;
  const identiconPngFile = `card_${num}_identicon.png`;
  fs.writeFileSync(path.join(identiconDir, identiconSvgFile), identiconSvg);
  fs.writeFileSync(path.join(identiconDir, identiconPngFile), identiconPng);

  // QR code — generate as SVG (no extra deps needed)
  const qrFile = `card_${num}_qr.txt`;
  // Store the wallet URL for QR generation (shopnfc can generate QR from data)
  fs.writeFileSync(path.join(qrcodeDir, qrFile), walletUrl);

  printRows.push({
    card_number: num,
    name: name,
    ln_address: lnAddress,
    wallet_url: walletUrl,
    identicon_file: `identicons/${identiconPngFile}`,
    qr_data: walletUrl,
  });

  console.log(`  ${num}: ${name} — ${lnAddress}`);
});

// Write print data CSV
const csvHeaders = ['card_number', 'name', 'ln_address', 'wallet_url', 'identicon_file', 'qr_data'];
const csvOut = [csvHeaders.join(',')];
printRows.forEach(row => {
  csvOut.push(csvHeaders.map(h => {
    const val = row[h] || '';
    return val.includes(',') ? `"${val}"` : val;
  }).join(','));
});

fs.writeFileSync(path.join(outputDir, 'print_data.csv'), csvOut.join('\n'));

// Write instructions for shopnfc
const instructions = `
SHOPNFC.COM VARIABLE DATA PRINTING INSTRUCTIONS
=================================================

Background: Use the template files (front/back) as the shared background.

Variable fields per card:
  - QR code (back): Generated from the "wallet_url" column in print_data.csv
  - Identicon (back): Use the SVG file from identicons/ folder
  - Lightning address text (back): From "ln_address" column
  - Name (front, optional): From "name" column

Files included:
  print_data.csv        — One row per card with all variable data
  identicons/           — SVG identicon per card (matches wallet identity)
  qrcodes/              — Wallet URL per card (for QR code generation)

Card dimensions:
  85.6 x 54 mm with 2mm bleed = 89.6 x 58 mm
  Safe area: 2mm inner margin

Number of unique cards: ${wallets.length}
`;

fs.writeFileSync(path.join(outputDir, 'INSTRUCTIONS.txt'), instructions.trim());

console.log(`\nDone! Output in ${outputDir}/`);
console.log(`  print_data.csv — send to shopnfc.com with your template`);
console.log(`  identicons/    — ${wallets.length} SVG identicons`);
console.log(`  qrcodes/       — ${wallets.length} wallet URLs for QR generation`);
console.log(`  INSTRUCTIONS.txt — printing instructions`);
