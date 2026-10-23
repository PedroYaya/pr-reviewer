// MSW intercepts fetch() at the network level: the app thinks it is talking
// to the real reviewer service.

import { delay, http, HttpResponse } from "msw";
import type { ReviewStatus } from "../api";
import { Simulator } from "./simulator";

export const simulator = new Simulator();

export const handlers = [
  http.get("/api/reviews", async ({ request }) => {
    await delay(150);
    const params = new URL(request.url).searchParams;
    const status = (params.get("status") as ReviewStatus | null) || null;
    const limit = Number(params.get("limit") ?? 50);
    return HttpResponse.json(simulator.list(status, limit));
  }),

  http.get("/api/reviews/:deliveryId", async ({ params }) => {
    await delay(100);
    const review = simulator.get(params.deliveryId as string);
    return review
      ? HttpResponse.json(review)
      : HttpResponse.json({ detail: "review not found" }, { status: 404 });
  }),

  http.get("/api/stats", async () => {
    await delay(100);
    return HttpResponse.json(simulator.stats());
  }),
];
