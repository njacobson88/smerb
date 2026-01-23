import admin from 'firebase-admin';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const serviceAccount = require('../Keys/r01-redditx-suicide-firebase-adminsdk-fbsvc-306bc4ee85.json');

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
});

const db = admin.firestore();

async function checkOcrResults() {
  console.log('Checking OCR results in Firebase...\n');

  // Get all OCR results
  const ocrSnapshot = await db.collection('ocr_results').orderBy('capturedAt', 'desc').limit(20).get();

  console.log(`Found ${ocrSnapshot.size} OCR results:\n`);

  ocrSnapshot.forEach((doc) => {
    const data = doc.data();
    console.log(`ID: ${doc.id}`);
    console.log(`  Participant: ${data.participantId}`);
    console.log(`  Word Count: ${data.wordCount}`);
    console.log(`  Processing Time: ${data.processingTimeMs}ms`);
    console.log(`  Captured At: ${data.capturedAt?.toDate?.() || data.capturedAt}`);
    console.log(`  Text Preview: ${data.extractedText?.substring(0, 100) || '(empty)'}...`);
    console.log('---');
  });

  // Summary stats
  const allOcr = await db.collection('ocr_results').get();
  let totalWords = 0;
  let emptyCount = 0;
  allOcr.forEach((doc) => {
    const data = doc.data();
    totalWords += data.wordCount || 0;
    if (!data.wordCount || data.wordCount === 0) emptyCount++;
  });

  console.log('\n=== Summary ===');
  console.log(`Total OCR results: ${allOcr.size}`);
  console.log(`Empty results (0 words): ${emptyCount}`);
  console.log(`Total words extracted: ${totalWords}`);

  process.exit(0);
}

checkOcrResults().catch(console.error);
