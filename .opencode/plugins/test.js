import { appendFileSync } from 'fs';

appendFileSync('/tmp/opencode-plugin.log', `Plugin loaded at ${new Date().toISOString()}\n`);

export default async () => {
  return {
    event: async ({ event }) => {
      appendFileSync('/tmp/opencode-plugin.log', `Event received: ${event.type}\n`);
      if (event.type === 'session.idle') {
        appendFileSync('/tmp/opencode-plugin.log', `✅ session.idle FIRED at ${Date.now()}\n`);
      }
    },
  };
};
