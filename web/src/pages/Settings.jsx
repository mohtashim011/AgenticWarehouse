import * as React from "react";
import { Settings as SettingsIcon, Loader2, Save, MessageSquareText, Send } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch, Separator } from "@/components/ui/misc";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";

export default function Settings() {
  const toast = useToast();
  const { can } = useAuth();
  const [groups, setGroups] = React.useState(null);
  const [values, setValues] = React.useState({});
  const [dirty, setDirty] = React.useState(false);
  const [saving, setSaving] = React.useState(false);

  const load = React.useCallback(async () => {
    const data = await api.settings();
    setGroups(data.described);
    setValues(data.settings);
    setDirty(false);
  }, []);

  React.useEffect(() => {
    load().catch((e) => toast.error(e.message));
  }, [load, toast]);

  const save = async () => {
    setSaving(true);
    try {
      const res = await api.saveSettings(values);
      toast.success(res.message);
      await load();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  if (!groups) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const editable = can("settings.manage");

  return (
    <div className="space-y-6">
      <Tabs defaultValue="system">
        <TabsList>
          <TabsTrigger value="system">System</TabsTrigger>
          <TabsTrigger value="assistant">Assistant</TabsTrigger>
        </TabsList>

        <TabsContent value="system" className="space-y-4">
          {!editable && (
            <Card className="border-dashed">
              <CardContent className="p-4 text-sm text-muted-foreground">
                These are shown for reference. Changing them needs the{" "}
                <code className="rounded bg-muted px-1">settings.manage</code> permission.
              </CardContent>
            </Card>
          )}

          {groups.map((g) => (
            <Card key={g.group}>
              <CardHeader>
                <CardTitle className="text-base">{g.group}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {g.settings.map((s, i) => (
                  <React.Fragment key={s.key}>
                    {i > 0 && <Separator />}
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <Label htmlFor={s.key} className="text-sm">{s.label}</Label>
                        <p className="mt-0.5 max-w-xl text-xs text-muted-foreground">{s.help}</p>
                        {values[s.key] !== s.default && (
                          <Badge variant="muted" className="mt-1.5">
                            default: {String(s.default)}
                          </Badge>
                        )}
                      </div>
                      <div className="shrink-0">
                        {s.type === "boolean" ? (
                          <Switch
                            id={s.key}
                            checked={Boolean(values[s.key])}
                            disabled={!editable}
                            onCheckedChange={(v) => {
                              setValues((p) => ({ ...p, [s.key]: v }));
                              setDirty(true);
                            }}
                          />
                        ) : (
                          <Input
                            id={s.key}
                            type={s.type === "number" ? "number" : "text"}
                            step="any"
                            className="w-44"
                            value={values[s.key] ?? ""}
                            disabled={!editable}
                            onChange={(e) => {
                              const v =
                                s.type === "number" ? Number(e.target.value) : e.target.value;
                              setValues((p) => ({ ...p, [s.key]: v }));
                              setDirty(true);
                            }}
                          />
                        )}
                      </div>
                    </div>
                  </React.Fragment>
                ))}
              </CardContent>
            </Card>
          ))}

          {editable && (
            <div className="sticky bottom-4 flex justify-end">
              <Button onClick={save} disabled={!dirty || saving} size="lg">
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {saving ? "Saving..." : dirty ? "Save changes" : "Saved"}
              </Button>
            </div>
          )}
        </TabsContent>

        <TabsContent value="assistant">
          <Assistant />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Assistant() {
  const toast = useToast();
  const [question, setQuestion] = React.useState("");
  const [answer, setAnswer] = React.useState(null);
  const [busy, setBusy] = React.useState(false);

  const suggestions = [
    "How many items are in stock?",
    "Which categories do we have?",
    "Are there any anomalies?",
    "What products are low on stock?",
  ];

  const ask = async (q) => {
    const text = (q ?? question).trim();
    if (!text) return;
    setBusy(true);
    try {
      setAnswer(await api.ask(text));
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageSquareText className="h-4 w-4" />
          Warehouse assistant
        </CardTitle>
        <CardDescription>
          Ask about current stock in plain language. Uses Claude when an API key is
          configured, and a built-in responder otherwise — it always answers.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask();
          }}
          className="flex gap-2"
        >
          <Input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="What is running low?"
          />
          <Button type="submit" disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            Ask
          </Button>
        </form>

        <div className="flex flex-wrap gap-2">
          {suggestions.map((s) => (
            <Button
              key={s}
              variant="outline"
              size="sm"
              onClick={() => {
                setQuestion(s);
                ask(s);
              }}
            >
              {s}
            </Button>
          ))}
        </div>

        {answer && (
          <div className="rounded-lg border p-4">
            <p className="whitespace-pre-wrap text-sm">{answer.answer}</p>
            <Badge variant="muted" className="mt-3">
              {answer.mode === "claude" ? `answered by ${answer.model}` : "answered offline"}
            </Badge>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
