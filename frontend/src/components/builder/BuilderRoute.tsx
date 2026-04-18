// BuilderRoute — dispatches /builder between editor and library.
//
// Lives in its own file (not App.tsx) so the entire builder bundle
// — ThesisBuilder, BuilderList, GraphCanvas, all sub-editors, validation —
// can be code-split out of the main chunk via React.lazy().

import { useSearchParams } from "react-router-dom";
import ThesisBuilder from "./ThesisBuilder";
import BuilderList from "./BuilderList";

export default function BuilderRoute() {
  const [params] = useSearchParams();
  const hasEdit = params.has("edit") || params.get("import") === "session";
  return hasEdit ? <ThesisBuilder /> : <BuilderList />;
}
