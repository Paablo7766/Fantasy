export interface Action {
  id: string;
  type: "buy" | "sell" | "wait";
  title: string;
  subtitle: string;
  value: string;
}

export interface MarketListing {
  id: string;
  name: string;
  position: string;
  team: string;
  probability: string;
  price: string;
  trend: { text: string; isUp: boolean };
  recommendedBid: string;
  analysis: { text: string; isPositive: boolean };
}

export interface DashboardData {
  balance: string;
  position: string;
  points: number;
  gameweek: string;
}

export interface SquadPlayer {
  id: string;
  name: string;
  position: string;
  team: string;
  pointsExpected: number;
  isStarter: boolean;
  matchStatus: "pending" | "playing" | "finished";
  matchTime: string;
  price: string;
}

export interface Rival {
  id: string;
  rank: number;
  name: string;
  points: number;
  maxBid: string;
  squadValue: string;
}
