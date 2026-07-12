// Deterministic layered LEFT-TO-RIGHT layout for the composer/model graph.
// Hand-rolled — no dagre/elk dependency.
//
// Ranking follows the edge direction: a node's rank is the length of the
// LONGEST directed path from it to a sink (a node with no outgoing edges).
// Columns are then assigned so sinks sit on the RIGHT and pure sources on the
// LEFT — i.e. inputs (participants / price_formation / policy / expectations /
// baseline, and the pe-shell's sector / technology_option grouping layer) fan
// out to the left, the market(s) sit toward the centre/right, and outputs
// (results / analysis) land on the far right. This "distance to sink" ranking
// keeps every DIRECT market input adjacent to the market instead of scattering
// pure sources to the far left.
//
// A model may be CYCLIC (linked / joint markets carry market_link back-edges):
// strongly-connected components are condensed to a DAG first (Tarjan), so the
// longest-path ranking always terminates and every market of a cyclic SCC
// shares one column.
//
// Within a column, nodes are ordered vertically by block category (inputs
// grouped by kind), then by their `order` param, then by id — the category
// bias the tie-break the ask calls for. Returns { [nodeId]: {x, y} }.

const COL_GAP = 280;
const ROW_GAP = 150;

// Vertical ordering within one column. Keyed by block category (note that
// participant / sector / technology_option all share the "participants"
// category — they are separated into columns by RANK, not category).
const CATEGORY_ROW_ORDER = {
  participants: 0,
  price_formation: 1,
  policy: 2,
  expectations: 3,
  baseline: 4,
  market: 5,
  analysis: 6,
};

function categoryRowRank(category) {
  const rank = CATEGORY_ROW_ORDER[category];
  return rank === undefined ? 9 : rank;
}

function orderValue(node) {
  const raw = node?.order;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : 0;
}

// Tarjan strongly-connected components. `ids` is the node id list; `adj` maps
// each id to a Set of successor ids. Returns { comp, compCount } where
// comp.get(id) is that node's component index.
function stronglyConnectedComponents(ids, adj) {
  let counter = 0;
  const index = new Map();
  const low = new Map();
  const onStack = new Set();
  const stack = [];
  const comp = new Map();
  let compCount = 0;

  const connect = (start) => {
    // Iterative Tarjan to avoid recursion limits on large graphs.
    const work = [[start, adj.get(start)[Symbol.iterator]()]];
    index.set(start, counter);
    low.set(start, counter);
    counter += 1;
    stack.push(start);
    onStack.add(start);
    while (work.length) {
      const frame = work[work.length - 1];
      const [v, iterator] = frame;
      const step = iterator.next();
      if (!step.done) {
        const w = step.value;
        if (!index.has(w)) {
          index.set(w, counter);
          low.set(w, counter);
          counter += 1;
          stack.push(w);
          onStack.add(w);
          work.push([w, adj.get(w)[Symbol.iterator]()]);
        } else if (onStack.has(w)) {
          low.set(v, Math.min(low.get(v), index.get(w)));
        }
        continue;
      }
      if (low.get(v) === index.get(v)) {
        let w;
        do {
          w = stack.pop();
          onStack.delete(w);
          comp.set(w, compCount);
        } while (w !== v);
        compCount += 1;
      }
      work.pop();
      if (work.length) {
        const parent = work[work.length - 1][0];
        low.set(parent, Math.min(low.get(parent), low.get(v)));
      }
    }
  };

  ids.forEach((id) => {
    if (!index.has(id)) connect(id);
  });
  return { comp, compCount };
}

// nodeList: [{ id, category, order? }]; edgeList: [{ source, target }].
// Returns positions keyed by node id.
function autoLayout(nodeList, edgeList) {
  const nodes = nodeList || [];
  if (!nodes.length) return {};
  const ids = nodes.map((node) => node.id);
  const idSet = new Set(ids);
  const nodeById = new Map(nodes.map((node) => [node.id, node]));

  const adj = new Map(ids.map((id) => [id, new Set()]));
  const hasEdge = new Set();
  (edgeList || []).forEach((edge) => {
    if (!edge || edge.source === edge.target) return;
    if (!idSet.has(edge.source) || !idSet.has(edge.target)) return;
    adj.get(edge.source).add(edge.target);
    hasEdge.add(edge.source);
    hasEdge.add(edge.target);
  });

  const { comp, compCount } = stronglyConnectedComponents(ids, adj);

  // Condensation adjacency (component -> set of successor components).
  const compAdj = new Map();
  for (let c = 0; c < compCount; c += 1) compAdj.set(c, new Set());
  adj.forEach((targets, src) => {
    const cs = comp.get(src);
    targets.forEach((t) => {
      const ct = comp.get(t);
      if (cs !== ct) compAdj.get(cs).add(ct);
    });
  });

  // Longest path to a sink on the condensation DAG (memoised).
  const compRank = new Map();
  const computeRank = (c) => {
    if (compRank.has(c)) return compRank.get(c);
    let best = 0;
    compAdj.get(c).forEach((t) => {
      best = Math.max(best, computeRank(t) + 1);
    });
    compRank.set(c, best);
    return best;
  };
  for (let c = 0; c < compCount; c += 1) computeRank(c);

  const maxRank = Math.max(0, ...Array.from(compRank.values()));

  // Column index: sinks (rank 0) on the RIGHT, pure sources on the LEFT.
  const columnOf = (id) => {
    if (!hasEdge.has(id)) {
      // Isolated node — place by category band so a stray input still lands
      // left, a stray market centre, a stray output right.
      const category = nodeById.get(id)?.category;
      if (category === "analysis") return maxRank;
      if (category === "market") return Math.floor(maxRank / 2);
      return 0;
    }
    return maxRank - compRank.get(comp.get(id));
  };

  const byColumn = new Map();
  ids.forEach((id) => {
    const column = columnOf(id);
    if (!byColumn.has(column)) byColumn.set(column, []);
    byColumn.get(column).push(id);
  });

  const positions = {};
  Array.from(byColumn.keys())
    .sort((a, b) => a - b)
    .forEach((column, columnIndex) => {
      const columnIds = byColumn.get(column).slice().sort((a, b) => {
        const na = nodeById.get(a);
        const nb = nodeById.get(b);
        const ca = categoryRowRank(na?.category);
        const cb = categoryRowRank(nb?.category);
        if (ca !== cb) return ca - cb;
        const oa = orderValue(na);
        const ob = orderValue(nb);
        if (oa !== ob) return oa - ob;
        return String(a).localeCompare(String(b));
      });
      const startY = -((columnIds.length - 1) * ROW_GAP) / 2;
      columnIds.forEach((id, rowIndex) => {
        positions[id] = { x: columnIndex * COL_GAP, y: startY + rowIndex * ROW_GAP };
      });
    });

  return positions;
}

export { autoLayout };
