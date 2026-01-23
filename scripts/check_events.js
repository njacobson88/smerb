import admin from 'firebase-admin';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const serviceAccount = require('../Keys/r01-redditx-suicide-firebase-adminsdk-fbsvc-306bc4ee85.json');

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
});

const db = admin.firestore();

async function checkEvents() {
  console.log('Checking events in Firebase...\n');

  // Get recent events
  const eventsSnapshot = await db.collection('events').orderBy('timestamp', 'desc').limit(10).get();

  console.log(`Found ${eventsSnapshot.size} recent events:\n`);

  eventsSnapshot.forEach((doc) => {
    const data = doc.data();
    console.log(`Type: ${data.eventType} | Participant: ${data.participantId}`);
    console.log(`  URL: ${data.url || '(none)'}`);
    console.log(`  Timestamp: ${data.timestamp?.toDate?.() || data.timestamp}`);
    console.log('---');
  });

  // Count by type
  const allEvents = await db.collection('events').get();
  const counts = {};
  allEvents.forEach((doc) => {
    const type = doc.data().eventType;
    counts[type] = (counts[type] || 0) + 1;
  });

  console.log('\n=== Event Summary ===');
  console.log(`Total events: ${allEvents.size}`);
  Object.entries(counts).forEach(([type, count]) => {
    console.log(`  ${type}: ${count}`);
  });

  process.exit(0);
}

checkEvents().catch(console.error);
