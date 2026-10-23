import { setupWorker } from "msw/browser";
import { handlers, simulator } from "./handlers";

const TICK_MS = 2_500;

export async function startMocks() {
  simulator.seed();
  setInterval(() => simulator.tick(), TICK_MS);
  await setupWorker(...handlers).start({ onUnhandledFrame: "bypass", quiet: true });
}
