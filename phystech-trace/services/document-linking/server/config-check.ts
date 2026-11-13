import { validateProductionSecrets } from "./config";

validateProductionSecrets(process.env);
console.log("Required production secrets passed validation");
