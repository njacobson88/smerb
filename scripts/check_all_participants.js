import admin from 'firebase-admin';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const serviceAccount = require('../Keys/r01-redditx-suicide-firebase-adminsdk-fbsvc-306bc4ee85.json');

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
});

const db = admin.firestore();

async function checkAll() {
  console.log('Checking all data in Firebase...\n');

  // Get all events
  const eventsSnapshot = await db.collection('events').limit(50).get();
  console.log(`=== Total events: ${eventsSnapshot.size} ===\n`);

  const participants = {};
  const typeCounts = {};
  let screenshotWithOcr = 0;

  eventsSnapshot.forEach((doc) => {
    const data = doc.data();
    const pid = data.participantId || 'unknown';
    participants[pid] = (participants[pid] || 0) + 1;
    typeCounts[data.eventType] = (typeCounts[data.eventType] || 0) + 1;

    if (data.eventType === 'screenshot' && data.ocrText) {
      screenshotWithOcr++;
      console.log(`Screenshot with OCR (${pid}):`);
      console.log(`  Words: ${data.ocrWordCount || 0}`);
      console.log(`  Text: "${(data.ocrText || '').substring(0, 200)}"`);
      console.log('---');
    }
  });

  console.log('\nParticipants:', participants);
  console.log('Event types:', typeCounts);
  console.log(`Screenshots with OCR text: ${screenshotWithOcr}`);

  // Check OCR results collection
  console.log('\n=== OCR Results collection ===');
  const ocrSnapshot = await db.collection('ocr_results').limit(20).get();
  console.log(`Total OCR results: ${ocrSnapshot.size}\n`);

  ocrSnapshot.forEach((doc) => {
    const data = doc.data();
    console.log(`Participant: ${data.participantId}, Words: ${data.wordCount}, Time: ${data.processingTimeMs}ms`);
    if (data.extractedText) {
      console.log(`  Text: "${data.extractedText.substring(0, 150)}"`);
    }
    console.log('---');
  });

  process.exit(0);
}

checkAll().catch(console.error);
