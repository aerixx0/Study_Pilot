using System;
using System.Diagnostics;
using System.IO;
using System.Text;

internal static class Launcher
{
    private static string Quote(string argument)
    {
        var result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char character in argument)
        {
            if (character == '\\')
            {
                slashes++;
                continue;
            }
            result.Append('\\', character == '"' ? 2 * slashes + 1 : slashes);
            result.Append(character);
            slashes = 0;
        }
        return result.Append('\\', 2 * slashes).Append('"').ToString();
    }

    public static int Main(string[] arguments)
    {
        string root = Directory.GetParent(AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\')).FullName;
        var parameters = new StringBuilder("-B -X utf8 ");
        parameters.Append(Quote(Path.Combine(root, @"app\start_studypilot.py")));
        if (arguments.Length == 0)
            parameters.Append(" --help");
        foreach (string argument in arguments)
            parameters.Append(' ').Append(Quote(argument));
        var info = new ProcessStartInfo(Path.Combine(root, @"runtime\python.exe"), parameters.ToString());
        info.UseShellExecute = false;
        try
        {
            using (var child = Process.Start(info))
            {
                // Both processes receive Ctrl+C. Allow Python to cancel and clean up its own worker.
                Console.CancelKeyPress += delegate(object sender, ConsoleCancelEventArgs e) { e.Cancel = true; };
                child.WaitForExit();
                return child.ExitCode;
            }
        }
        catch (System.ComponentModel.Win32Exception)
        {
            Console.Error.WriteLine("StudyPilot could not start its bundled Python. Reinstall StudyPilot.");
            return 1;
        }
    }
}
